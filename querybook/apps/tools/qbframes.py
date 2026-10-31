#!/usr/bin/env python3
"""Frame interpolation and upscaling for QueryBook's hybrid video renderer.

Two backends each, chosen automatically:

  interpolation  RIFE (rife-ncnn-vulkan: an AI frame interpolator, MIT licence, runs on the graphics card) when it is
                 installed; otherwise ffmpeg's motion-compensated interpolation (minterpolate, CPU: about 14 s per second
                 of 720p video on 4 cores — measured); "fast" duplicates frames instead (no new motion, seconds).
  upscaling      Real-ESRGAN (realesrgan-ncnn-vulkan: an AI upscaler, BSD-3 licence, graphics card) when installed;
                 otherwise ffmpeg Lanczos + light sharpening (about 2 s per second of 720p→1440p video on 4 cores).

The AI programs are looked up on PATH or in the folder named by QB_AI_TOOLS. They are separate free programs the
admin installs (keep their licence notices); QueryBook calls them on folders of frames and reassembles the video.

Where this saves time: a JOIN between two stored clips is bridged by interpolated frames instead of a generated
clip (seconds instead of a video-model call), when the two ends are similar enough for in-between frames to look
right; otherwise the join is a cross-fade. Interpolating or upscaling a whole clip ADDS time; it buys smoothness
(real slow motion, 60 frames per second) and sharpness, and the plan says what it costs.
"""
import glob, os, shutil, subprocess, tempfile

TOOLS = {"rife": "rife-ncnn-vulkan", "esrgan": "realesrgan-ncnn-vulkan"}


def find_tool(name):
    exe = TOOLS[name] + (".exe" if os.name == "nt" else "")
    for d in [os.environ.get("QB_AI_TOOLS", "")] + os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        for p in (os.path.join(d, exe), os.path.join(d, TOOLS[name], exe)):
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    return None


def backends():
    return {"interpolation": "RIFE (AI, graphics card)" if find_tool("rife") else "ffmpeg minterpolate (CPU)",
            "upscaling": "Real-ESRGAN (AI, graphics card)" if find_tool("esrgan") else "ffmpeg Lanczos (CPU)"}


def _ff(args, timeout=1800):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + args, capture_output=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError("ffmpeg: %s" % r.stderr.decode("utf-8", "replace")[-300:])


def _probe(path, entries="stream=width,height,r_frame_rate"):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", entries, "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return r.stdout.strip().split(",")


def size(path):
    w, h, *_ = _probe(path)
    return int(w), int(h)


def fps(path):
    a, b = _probe(path, "stream=r_frame_rate")[0].split("/")
    return float(a) / float(b or 1)


def _frames(src, folder, extra=None):
    os.makedirs(folder, exist_ok=True)
    _ff(["-i", src] + (extra or []) + [os.path.join(folder, "%08d.png")])
    return sorted(glob.glob(os.path.join(folder, "*.png")))


def _assemble(folder, rate, dst):
    _ff(["-framerate", str(rate), "-i", os.path.join(folder, "%08d.png"), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", dst])


def _renumber(folder):
    for i, p in enumerate(sorted(glob.glob(os.path.join(folder, "*.png"))), 1):
        os.replace(p, os.path.join(folder, "tmp_%08d.png" % i))
    for p in glob.glob(os.path.join(folder, "tmp_*.png")):
        os.replace(p, os.path.join(folder, os.path.basename(p)[4:]))


# ------------------------------------------------------------------------------------------------ interpolation
def interpolate(src, dst, target_fps=None, slow=1.0, mode="best"):
    """a clip with new in-between frames: at target_fps, and/or slow motion (slow=0.5 → half speed, smooth).
    mode "fast" duplicates frames (no new motion). Returns the backend used."""
    f0 = fps(src)
    out_fps = target_fps or f0
    factor = (out_fps / f0) / slow                     # frames needed per source frame
    if mode == "fast" or factor <= 1.0001:
        vf = ([] if slow == 1.0 else ["setpts=%f*PTS" % (1.0 / slow)]) + ["fps=%s" % out_fps]
        _ff(["-i", src, "-vf", ",".join(vf), "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", dst])
        return "frame duplication"
    rife = find_tool("rife")
    if rife:
        tmp = tempfile.mkdtemp(prefix="qb-rife-")
        try:
            frames = _frames(src, os.path.join(tmp, "in"))
            n = int(round(len(frames) * factor))
            os.makedirs(os.path.join(tmp, "out"))
            r = subprocess.run([rife, "-i", os.path.join(tmp, "in"), "-o", os.path.join(tmp, "out"), "-n", str(n), "-f", "%08d.png"],
                               capture_output=True, timeout=3600)
            if r.returncode or not glob.glob(os.path.join(tmp, "out", "*.png")):
                raise RuntimeError("RIFE failed: %s" % r.stderr.decode("utf-8", "replace")[-200:])
            _renumber(os.path.join(tmp, "out"))
            _assemble(os.path.join(tmp, "out"), out_fps, dst)
            return "RIFE"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    vf = ([] if slow == 1.0 else ["setpts=%f*PTS" % (1.0 / slow)]) + ["minterpolate=fps=%s:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1" % out_fps]
    _ff(["-i", src, "-vf", ",".join(vf), "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", dst])
    return "ffmpeg minterpolate"


def frame_difference(a_png, b_png):
    """how different two frames are, 0 (identical) .. 255, on small grey copies"""
    vals = []
    for p in (a_png, b_png):
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", p, "-vf", "scale=64:36,format=gray", "-f", "rawvideo", "-"],
                           capture_output=True)
        vals.append(r.stdout)
    a, b = vals
    n = min(len(a), len(b))
    return sum(abs(x - y) for x, y in zip(a[:n], b[:n])) / max(1, n)


def bridge(a_clip, b_clip, dst, seconds=0.5, rate=24, max_difference=40.0):
    """in-between frames from the last frame of a_clip to the first frame of b_clip — or None when the two ends differ
    too much for in-between frames to look right (the caller cross-fades instead). Returns (backend, difference)."""
    tmp = tempfile.mkdtemp(prefix="qb-bridge-")
    try:
        a_last, b_first = os.path.join(tmp, "a.png"), os.path.join(tmp, "b.png")
        _ff(["-sseof", "-0.1", "-i", a_clip, "-frames:v", "1", "-update", "1", a_last])
        _ff(["-i", b_clip, "-frames:v", "1", b_first])
        diff = frame_difference(a_last, b_first)
        if diff > max_difference:
            return None, round(diff, 1)
        n = max(2, int(round(seconds * rate)))
        rife = find_tool("rife")
        out = os.path.join(tmp, "out")
        os.makedirs(out)
        if rife:
            ind = os.path.join(tmp, "in")
            os.makedirs(ind)
            shutil.copyfile(a_last, os.path.join(ind, "00000001.png"))
            shutil.copyfile(b_first, os.path.join(ind, "00000002.png"))
            r = subprocess.run([rife, "-i", ind, "-o", out, "-n", str(n + 2), "-f", "%08d.png"], capture_output=True, timeout=600)
            if r.returncode:
                raise RuntimeError("RIFE failed: %s" % r.stderr.decode("utf-8", "replace")[-200:])
            frames = sorted(glob.glob(os.path.join(out, "*.png")))[1:-1]     # the ends are the clips' own frames
            for p in sorted(glob.glob(os.path.join(out, "*.png"))):
                if p not in frames:
                    os.remove(p)
            _renumber(out)
            backend = "RIFE"
        else:
            # minterpolate needs context on both sides: each end is held for 2 s at 1 frame a second (a a b b), so the
            # frames it makes between t=1 s and t=2 s are the in-between frames from a to b
            pair = os.path.join(tmp, "pair.mp4")
            _ff(["-loop", "1", "-t", "2", "-i", a_last, "-loop", "1", "-t", "2", "-i", b_first, "-filter_complex",
                 "[0:v][1:v]concat=n=2:v=1,fps=1", "-pix_fmt", "yuv420p", pair])
            allf = os.path.join(tmp, "all")
            os.makedirs(allf)
            _ff(["-i", pair, "-vf", "minterpolate=fps=%d:mi_mode=mci:mc_mode=aobmc:me_mode=bidir" % (n + 1), os.path.join(allf, "%08d.png")])
            frames = sorted(glob.glob(os.path.join(allf, "*.png")))[n + 2:2 * n + 2]
            if len(frames) < n:
                raise RuntimeError("interpolation made %d of %d in-between frames" % (len(frames), n))
            for k, p in enumerate(frames, 1):
                shutil.copyfile(p, os.path.join(out, "%08d.png" % k))
            backend = "ffmpeg minterpolate"
        _assemble(out, rate, dst)
        return backend, round(diff, 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------------------------------------ upscaling
def upscale(src, dst, height):
    """the clip at the given height (width kept in proportion, even). Returns the backend used."""
    w, h = size(src)
    if height <= h:
        _ff(["-i", src, "-vf", "scale=-2:%d:flags=lanczos" % height, "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", dst])
        return "downscale (Lanczos)"
    esr = find_tool("esrgan")
    if esr:
        tmp = tempfile.mkdtemp(prefix="qb-esrgan-")
        try:
            rate = fps(src)
            _frames(src, os.path.join(tmp, "in"))
            os.makedirs(os.path.join(tmp, "out"))
            s = 4 if height > 2 * h else 2
            r = subprocess.run([esr, "-i", os.path.join(tmp, "in"), "-o", os.path.join(tmp, "out"), "-s", str(s), "-f", "png"],
                               capture_output=True, timeout=7200)
            if r.returncode or not glob.glob(os.path.join(tmp, "out", "*.png")):
                raise RuntimeError("Real-ESRGAN failed: %s" % r.stderr.decode("utf-8", "replace")[-200:])
            big = os.path.join(tmp, "big.mp4")
            _assemble(os.path.join(tmp, "out"), rate, big)
            _ff(["-i", big, "-vf", "scale=-2:%d:flags=lanczos" % height, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", dst])
            return "Real-ESRGAN"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    _ff(["-i", src, "-vf", "scale=-2:%d:flags=lanczos,unsharp=5:5:0.5" % height, "-an", "-c:v", "libx264", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", dst])
    return "ffmpeg Lanczos"


def ssim(a, b):
    """structural similarity of two clips of the same length (b scaled to a's size): 1.0 = identical"""
    w, h = size(a)
    r = subprocess.run(["ffmpeg", "-loglevel", "info", "-i", a, "-i", b, "-lavfi", "[1:v]scale=%d:%d[b];[0:v][b]ssim" % (w, h), "-f", "null", "-"],
                       capture_output=True, text=True)
    for line in r.stderr.splitlines()[::-1]:
        if "All:" in line:
            try:
                return float(line.split("All:")[1].split()[0])
            except (IndexError, ValueError):
                break
    return 0.0
