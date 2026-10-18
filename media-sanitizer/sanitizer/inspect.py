"""Inspection: what identifying data a file carries and where it sits.

Covers what can be found from the file alone: container boxes/chunks with byte
offsets, byte signatures (config/signatures.json), and persistent visible
overlays (logos, bugs) with their frame position. Invisible signal watermarks
cannot be found this way - see NOT_CHECKED.
"""

import json
import os
import struct
import subprocess
import uuid

from .config import CONFIG_DIR

KNOWN_UUIDS = {
    "d8fec3d6-1b0e-483c-9297-5828877ec481": ("C2PA content credentials manifest", "provenance"),
    "be7acfcb-97a9-42e8-9c71-999491e3afac": ("XMP metadata packet", "metadata"),
}
# ISO-BMFF boxes that only hold other boxes.
MP4_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"udta", b"edts", b"dinf", b"moof", b"traf", b"mvex"}
# Item names inside udta / ilst worth spelling out; anything else is reported by its 4cc.
MP4_ITEM_NAMES = {
    b"\xa9nam": "title", b"\xa9ART": "artist", b"\xa9cmt": "comment", b"\xa9too": "encoding tool",
    b"\xa9swr": "software", b"\xa9xyz": "GPS location", b"\xa9day": "date", b"\xa9des": "description",
    b"desc": "description", b"cprt": "copyright", b"\xa9mak": "device make", b"\xa9mod": "device model",
    b"XMP_": "XMP metadata", b"name": "track name",
}
MP4_ITEM_CATEGORY = {b"\xa9too": "encoder", b"\xa9swr": "encoder", b"XMP_": "metadata"}
# Structural children that hold nothing descriptive on their own.
MP4_STRUCTURAL = {b"hdlr", b"ilst", b"keys", b"free", b"meta"}
RIFF_FLAGGED = {
    b"LIST": ("INFO/LIST tags", "metadata"),
    b"bext": ("Broadcast WAV description (originator, dates)", "metadata"),
    b"iXML": ("iXML production metadata", "metadata"),
    b"id3 ": ("embedded ID3 tag", "metadata"),
    b"ID3 ": ("embedded ID3 tag", "metadata"),
    b"_PMX": ("XMP metadata", "metadata"),
    b"axml": ("XML metadata", "metadata"),
}

NOT_CHECKED = [
    "Invisible signal watermarks (for example SynthID, AudioSeal, Digimarc-style marks) are spread "
    "imperceptibly through the whole picture or waveform. They have no single location, and only the "
    "issuing vendor's detector can confirm one. Re-encoding does not reliably remove them.",
    "Statistical traits of generated content (spectral or motion patterns) are judgements made by "
    "classifiers, not data stored in the file.",
]


def load_signatures(path=None):
    with open(path or os.path.join(CONFIG_DIR, "signatures.json"), encoding="utf-8") as fh:
        rows = json.load(fh)["signatures"]
    return [dict(r, pattern=bytes.fromhex(r["hex"]) if "hex" in r else r["text"].encode()) for r in rows]


def scan_signatures(path, signatures, max_hits=5, chunk=8 << 20):
    """Stream the file once; return each matching signature with its first byte offsets."""
    overlap = max(len(s["pattern"]) for s in signatures) - 1
    hits = {s["name"]: [] for s in signatures}
    counts = dict.fromkeys(hits, 0)
    with open(path, "rb") as fh:
        pos, tail = 0, b""
        while True:
            block = fh.read(chunk)
            if not block:
                break
            data, base = tail + block, pos - len(tail)
            for s in signatures:
                start = 0
                while True:
                    i = data.find(s["pattern"], start)
                    # matches inside the overlap were already counted last round
                    if i < 0:
                        break
                    if i + len(s["pattern"]) > len(tail):
                        counts[s["name"]] += 1
                        if len(hits[s["name"]]) < max_hits:
                            hits[s["name"]].append(base + i)
                    start = i + 1
            pos += len(block)
            tail = data[-overlap:] if overlap else b""
    return [{"kind": "signature", "name": s["name"], "category": s["category"],
             "count": counts[s["name"]], "offsets": hits[s["name"]]}
            for s in signatures if counts[s["name"]]]


def _item_value(fh, pos, size, hdr, kind):
    """Best-effort printable preview of an ilst/udta item's payload."""
    fh.seek(pos + hdr)
    payload = fh.read(min(size - hdr, 200))
    data = payload.find(b"data")
    if data >= 0:  # iTunes-style: data atom, 8 bytes of type/locale
        text = payload[data + 12:]
    elif kind[:1] == b"\xa9":  # QuickTime user data text: 2-byte length + 2-byte language
        text = payload[4:]
    else:
        text = payload
    text = text.decode("utf-8", "replace").strip("\x00").strip()
    return "".join(ch for ch in text if ch.isprintable())[:80]


def _mp4_walk(fh, start, end, depth, out, path_, parent=b""):
    pos = start
    while pos + 8 <= end:
        fh.seek(pos)
        header = fh.read(16)
        if len(header) < 8:
            return
        size, kind = struct.unpack(">I4s", header[:8])
        hdr = 8
        if size == 1:
            size, hdr = struct.unpack(">Q", header[8:16])[0], 16
        elif size == 0:
            size = end - pos
        if size < hdr or pos + size > end:
            return
        name = path_ + "/" + kind.decode("latin-1")
        entry = {"kind": "box", "box": name, "offset": pos, "size": size}
        if kind == b"uuid":
            fh.seek(pos + hdr)
            u = str(uuid.UUID(bytes=fh.read(16)))
            label, cat = KNOWN_UUIDS.get(u, (f"unknown uuid box {u}", "unknown"))
            out.append(dict(entry, name=label, category=cat))
        elif parent in (b"udta", b"ilst") and kind not in MP4_STRUCTURAL:
            label = MP4_ITEM_NAMES.get(kind, "metadata item " + kind.decode("latin-1"))
            out.append(dict(entry, name=label, category=MP4_ITEM_CATEGORY.get(kind, "metadata"),
                            value=_item_value(fh, pos, size, hdr, kind)))
        if depth < 8 and (kind in MP4_CONTAINERS or kind == b"ilst"):
            _mp4_walk(fh, pos + hdr, pos + size, depth + 1, out, name, kind)
        elif depth < 8 and kind == b"meta":  # full box: 4 bytes version/flags first
            fh.seek(pos + hdr)
            skip = 0 if fh.read(8)[4:8] == b"hdlr" else 4  # QuickTime meta has no version field
            _mp4_walk(fh, pos + hdr + skip, pos + size, depth + 1, out, name, kind)
        pos += size


def container_findings(path):
    size = os.path.getsize(path)
    out = []
    with open(path, "rb") as fh:
        head = fh.read(12)
        if head[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"wide"):
            _mp4_walk(fh, 0, size, 0, out, "")
        elif head[:4] == b"RIFF" and head[8:12] in (b"WAVE", b"AVI "):
            pos = 12
            while pos + 8 <= size:
                fh.seek(pos)
                cid, csize = struct.unpack("<4sI", fh.read(8))
                if cid in RIFF_FLAGGED:
                    label, cat = RIFF_FLAGGED[cid]
                    out.append({"kind": "chunk", "box": cid.decode("latin-1"), "offset": pos,
                                "size": csize + 8, "name": label, "category": cat})
                pos += 8 + csize + (csize & 1)
        if size > 128:
            fh.seek(size - 128)
            if fh.read(3) == b"TAG":
                out.append({"kind": "chunk", "box": "ID3v1", "offset": size - 128, "size": 128,
                            "name": "ID3v1 tag", "category": "metadata"})
    return out


def _region_label(x0, y0, x1, y1, w, h):
    cx, cy = (x0 + x1) / 2 / w, (y0 + y1) / 2 / h
    vert = "top" if cy < 1 / 3 else "bottom" if cy > 2 / 3 else "middle"
    horiz = "left" if cx < 1 / 3 else "right" if cx > 2 / 3 else "center"
    return "center" if vert == "middle" and horiz == "center" else f"{vert}-{horiz}"


def visual_overlays(path, probe_info, ffmpeg="ffmpeg", frames=40, gw=96, gh=54):
    """Find regions that stay pixel-identical with visible edges while the rest of the picture changes.

    Returns {"status": ..., "regions": [...]} with boxes in source-pixel coordinates.
    """
    video = next((s for s in probe_info["streams"] if s["codec_type"] == "video"), None)
    duration = probe_info.get("duration") or 0
    if not video or duration <= 0:
        return {"status": "no video", "regions": []}
    width, height = video.get("width") or 0, video.get("height") or 0
    fps = max(0.05, min(10.0, frames / duration))
    cmd = [ffmpeg, "-v", "error", "-nostdin", "-i", path, "-an", "-vf",
           f"fps={fps:.4f},scale={gw}:{gh},format=gray", "-frames:v", str(frames),
           "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (gw * gh)
    if n < 8:
        return {"status": "too short to judge", "regions": []}
    planes = [raw[i * gw * gh:(i + 1) * gw * gh] for i in range(n)]
    npx = gw * gh
    mean, std = [0.0] * npx, [0.0] * npx
    for p in range(npx):
        vals = [pl[p] for pl in planes]
        m = sum(vals) / n
        mean[p] = m
        std[p] = (sum((v - m) ** 2 for v in vals) / n) ** 0.5
    if sorted(std)[npx // 2] < 3:
        return {"status": "picture too static to separate overlays from content", "regions": []}

    cand = [False] * npx
    for y in range(1, gh - 1):
        for x in range(1, gw - 1):
            p = y * gw + x
            edge = abs(mean[p + 1] - mean[p - 1]) + abs(mean[p + gw] - mean[p - gw])
            cand[p] = std[p] < 2.5 and edge > 20
    cw = ch = 6  # cell size in grid pixels
    cols, rows = gw // cw, gh // ch
    cells = set()
    for r in range(rows):
        for c in range(cols):
            hit = sum(cand[(r * ch + y) * gw + c * cw + x] for y in range(ch) for x in range(cw))
            if hit >= 4:
                cells.add((r, c))
    regions, seen = [], set()
    for cell in sorted(cells):
        if cell in seen:
            continue
        stack, comp = [cell], []
        seen.add(cell)
        while stack:
            r, c = stack.pop()
            comp.append((r, c))
            for nb in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if nb in cells and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        if len(comp) > rows * cols // 4:
            continue  # a frozen half of the picture is content, not an overlay
        r0, r1 = min(r for r, _ in comp), max(r for r, _ in comp) + 1
        c0, c1 = min(c for _, c in comp), max(c for _, c in comp) + 1
        sx, sy = width / gw, height / gh
        x0, y0, x1, y1 = int(c0 * cw * sx), int(r0 * ch * sy), int(c1 * cw * sx), int(r1 * ch * sy)
        regions.append({"kind": "overlay", "name": "persistent static region (logo, bug or burned-in text)",
                        "category": "visual", "position": _region_label(x0, y0, x1, y1, width, height),
                        "box": {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}, "frames_sampled": n})
    return {"status": "checked", "regions": regions}


def inspect(path, probe_info, settings, signatures=None):
    opts = settings.get("inspection", {})
    sigs = signatures if signatures is not None else load_signatures()
    findings = container_findings(path) + scan_signatures(path, sigs, opts.get("max_signature_hits", 5))
    overlay = {"status": "skipped", "regions": []}
    if opts.get("visual_overlays", True):
        overlay = visual_overlays(path, probe_info, settings["ffmpeg"], opts.get("overlay_frames", 40))
    findings += overlay["regions"]
    return {"findings": findings, "overlay_check": overlay["status"], "not_checked": NOT_CHECKED}
