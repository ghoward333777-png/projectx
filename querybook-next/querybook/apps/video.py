"""Video-generation app — answers come back as a storyboard (timed scenes with
narration and a visual brief) built from the whole shared corpus, saved as a
render job in the Video collection, and rendered to MP4 when ffmpeg is present."""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from typing import Any

from querybook.apps.base import DomainApp, QueryContext, fql_str, source_ref
from querybook.core.model import DOMAIN_COLLECTIONS
from querybook.core.text import classify, normalize_ws, sentences, tokenize

WORDS_PER_SECOND = 2.6
PALETTE = {"title": "0x1B2A41", "language": "0x5B3A8C", "stem": "0x0E6E62", "history": "0x8A4B1F",
           "video": "0x2F4858", "outro": "0x1B2A41"}
SHOT_WORDS = ("wide", "close-up", "closeup", "pan", "zoom", "tracking", "aerial", "montage", "b-roll", "dolly")
FONT_CANDIDATES = (
    "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",                    # Windows
    "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",       # macOS
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",  # Linux
)
_render_lock = threading.Lock()


def clip_words(text: str, limit: int) -> str:
    words = normalize_ws(text).split()
    return " ".join(words) if len(words) <= limit else " ".join(words[:limit]).rstrip(",;:") + "…"


def srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(scenes: list[dict[str, Any]]) -> str:
    blocks = []
    for i, sc in enumerate(scenes, 1):
        blocks.append(f"{i}\n{srt_time(sc['start'])} --> {srt_time(sc['end'])}\n{textwrap.fill(sc['narration'], 48)}\n")
    return "\n".join(blocks)


def find_font() -> str | None:
    return next((f for f in FONT_CANDIDATES if Path(f).is_file()), None)


def _ff_path(p: Path | str) -> str:
    """Escape a path for an ffmpeg filter option (handles Windows drive colons)."""
    return "'" + str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'") + "'"


class VideoApp(DomainApp):
    key = "video"
    title = "Video Studio"
    collection = DOMAIN_COLLECTIONS["video"]
    tagline = "Storyboards and rendered explainers from the shared corpus"
    placeholder = "Video topic — e.g. the printing press"
    examples = ("the printing press", "Newton's laws of motion", "where English words come from")

    def enrich(self, title: str, body: str) -> dict[str, Any]:
        text = f"{title}\n{body}"
        low = text.lower()
        words = len(text.split())
        return {"est_duration_s": round(words / WORDS_PER_SECOND, 1),
                "shots": [s for s in SHOT_WORDS if s in low],
                "scene_count": max(1, low.count("scene ") or body.count("\n\n") + 1)}

    # -- storyboard --------------------------------------------------------
    def storyboard(self, ctx: QueryContext, topic: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        hits: dict[str, list[dict[str, Any]]] = {}
        for domain, coll in DOMAIN_COLLECTIONS.items():
            hits[domain] = [d for d in ctx.docs(f"{coll}.search({fql_str(topic)}).take(3)") if d.get("kind") != "render_job"]
        guess, _ = classify(topic)
        # Lead with the domain that knows most about the topic; the rest add one scene each.
        order = sorted(DOMAIN_COLLECTIONS, key=lambda d: (-len(hits[d]), d != guess, list(DOMAIN_COLLECTIONS).index(d)))
        picked: list[dict[str, Any]] = []
        for i, domain in enumerate(order):
            picked += hits[domain][: (3 if i == 0 else 1)]
        picked = picked[:6]
        scenes: list[dict[str, Any]] = []
        t = 0.0

        def add(kind: str, heading: str, narration: str, visual: str, doc: dict[str, Any] | None = None) -> None:
            nonlocal t
            dur = max(4.0, round(len(narration.split()) / WORDS_PER_SECOND, 1))
            scenes.append({"n": len(scenes) + 1, "kind": kind, "heading": heading, "narration": narration,
                           "visual": visual, "start": round(t, 2), "end": round(t + dur, 2), "duration": dur,
                           "color": PALETTE.get(kind, PALETTE["video"]),
                           "source": source_ref(doc) if doc else None})
            t += dur

        title = topic[:1].upper() + topic[1:]
        add("title", title, f"{title}: what it is, where it came from, and why it matters.",
            f"Title card — “{title}” over a slow push-in on a related image.")
        per_doc = 3 if len(picked) <= 2 else 1  # a sparse topic gets one scene per paragraph instead
        for doc in picked:
            domain = next((k for k, v in DOMAIN_COLLECTIONS.items() if v == doc.get("coll")), "video")
            paragraphs = [p for p in (doc.get("body") or "").split("\n\n") if p.strip()] or [doc.get("title", "")]
            for part, para in enumerate(paragraphs[:per_doc]):
                narration = clip_words(" ".join(sentences(para)[:2]) or para, 42)
                heading = clip_words(doc.get("title") or doc.get("term") or title, 8)
                if part:
                    heading = f"{heading} ({part + 1})"
                if domain == "history":
                    years = [e["label"] for e in (doc.get("events") or []) if e.get("text", "") in para][:3]
                    visual = f"Archival-style stills with a dated timeline strip ({', '.join(years) or 'undated'})."
                elif domain == "stem":
                    f = next((f["expr"] for f in (doc.get("formulas") or []) if f["rhs"] in para), None)
                    visual = f"Animated diagram building up {f}." if f else f"Animated diagram explaining {heading}."
                elif domain == "language":
                    visual = f"Kinetic typography: “{doc.get('term') or heading}” with its meaning drawn underneath."
                else:
                    visual = "Footage per the source script: " + ", ".join(doc.get("shots") or ["wide establishing shot"]) + "."
                add(domain, heading, narration, visual, doc)
        if picked:
            first = (sentences(picked[0].get("body", "")) or [""])[0]
            add("outro", "Key idea", clip_words(first, 30) or title, "Recap card listing the sources on screen.")
        else:
            add("outro", "More to come", f"There is not much about {topic} in the library yet.",
                "Plain card inviting viewers to send sources.")
        return scenes, picked

    def respond(self, ctx: QueryContext, query: str) -> dict[str, Any]:
        topic = normalize_ws(query).rstrip("?.")
        scenes, picked = self.storyboard(ctx, topic)
        duration = scenes[-1]["end"] if scenes else 0
        srt = build_srt(scenes)
        job = {"kind": "render_job", "title": topic, "topic_tokens": tokenize(topic), "status": "storyboarded",
               "scenes": scenes, "duration_s": duration, "srt": srt, "video_file": None,
               "source_ids": [d.get("id") for d in picked]}
        ctx.fql_log.append(f"Video.create({{ kind: \"render_job\", title: {fql_str(topic)}, scenes: [{len(scenes)} scenes], … }})")
        doc, created = ctx.store.create(self.collection, job)
        saved = doc.to_json()
        return {"kind": "storyboard", "subject": topic, "summary": f"{len(scenes)} scenes, {duration:.0f} seconds, from "
                f"{len(picked)} source{'s' if len(picked) != 1 else ''}.",
                "job": {"id": saved["id"], "status": saved.get("status"), "video_file": saved.get("video_file"),
                        "created": created},
                "scenes": scenes, "duration_s": duration, "srt": srt,
                "renderer": {"ffmpeg": bool(shutil.which("ffmpeg")), "font": bool(find_font())},
                "sources": [source_ref(d) for d in picked]}

    # -- rendering -----------------------------------------------------------
    def start_render(self, store: Any, job_id: str, renders_dir: Path, *, wait: bool = False) -> dict[str, Any]:
        doc = store.get(self.collection, job_id)
        if doc is None or doc.data.get("kind") != "render_job":
            return {"ok": False, "error": "No such render job"}
        if not shutil.which("ffmpeg"):
            store.update(self.collection, job_id, {"status": "needs_ffmpeg"})
            return {"ok": False, "error": "ffmpeg is not installed. Windows: winget install ffmpeg · macOS: brew install ffmpeg"}
        if doc.data.get("status") == "rendering":
            return {"ok": True, "status": "rendering"}
        store.update(self.collection, job_id, {"status": "rendering", "error": None})
        worker = threading.Thread(target=self._render, args=(store, job_id, Path(renders_dir)), daemon=True)
        worker.start()
        if wait:
            worker.join()
        return {"ok": True, "status": "rendering"}

    def _render(self, store: Any, job_id: str, renders_dir: Path) -> None:
        with _render_lock:
            doc = store.get(self.collection, job_id)
            if doc is None:
                return
            scenes = doc.data.get("scenes") or []
            work = renders_dir / f"job-{job_id}"
            work.mkdir(parents=True, exist_ok=True)
            srt = work / "captions.srt"
            srt.write_text(doc.data.get("srt", ""), encoding="utf-8")
            out = renders_dir / f"{job_id}.mp4"
            font = find_font()
            parts = []
            for i, sc in enumerate(scenes):
                chain = f"color=c={sc['color']}:s=1280x720:r=24:d={sc['duration']}"
                if font:
                    card = work / f"scene{i}.txt"
                    card.write_text(textwrap.fill(sc["heading"], 34) + "\n\n" + textwrap.fill(sc["narration"], 52),
                                    encoding="utf-8")
                    chain += (f",drawtext=fontfile={_ff_path(font)}:textfile={_ff_path(card)}:expansion=none"
                              ":fontcolor=white:fontsize=34:line_spacing=14:x=(w-text_w)/2:y=(h-text_h)/2")
                parts.append(f"{chain}[v{i}]")
            graph = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(len(scenes))) + \
                f"concat=n={len(scenes)}:v=1:a=0,format=yuv420p[out]"
            codec = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]
            probe = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
            if "libx264" not in probe.stdout:
                codec = ["-c:v", "mpeg4", "-q:v", "4"]
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(srt), "-filter_complex", graph,
                   "-map", "[out]", "-map", "0:s", *codec, "-c:s", "mov_text", "-movflags", "+faststart", str(out)]
            flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0  # no console flash on Windows
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, creationflags=flags)
                ok = proc.returncode == 0 and out.is_file()
                error = None if ok else (proc.stderr.strip()[-800:] or "ffmpeg failed")
            except (OSError, subprocess.TimeoutExpired) as exc:
                ok, error = False, str(exc)
            store.update(self.collection, job_id, {"status": "rendered" if ok else "failed",
                                                   "video_file": out.name if ok else None, "error": error})
