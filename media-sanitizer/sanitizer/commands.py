"""Turn a preset (plain dict from presets.json) into an ffmpeg argument list."""

import os

EXTENSIONS = {"mp4": ".mp4", "mov": ".mov", "mkv": ".mkv"}


def output_path_for(input_path, output_dir, preset, suffix="_clean"):
    stem, ext = os.path.splitext(os.path.basename(input_path))
    container = preset.get("container", "source")
    return os.path.join(output_dir, stem + suffix + EXTENSIONS.get(container, ext))


def _video_args(video):
    codec = video["codec"]
    args = ["-c:v", codec]
    if codec in ("libx264", "libx265"):
        args += ["-crf", str(video.get("crf", 18)), "-preset", video.get("preset", "medium")]
        if video.get("profile"):
            args += ["-profile:v", str(video["profile"])]
    elif codec == "prores_ks":
        args += ["-profile:v", str(video.get("profile", 3))]
    elif codec == "ffv1":
        args += ["-level", "3", "-g", "1", "-slicecrc", "1"]
    if video.get("pix_fmt"):
        args += ["-pix_fmt", video["pix_fmt"]]
    return args


def _audio_args(audio):
    args = ["-c:a", audio["codec"]]
    if audio.get("bitrate"):
        args += ["-b:a", str(audio["bitrate"])]
    if audio.get("sample_rate"):
        args += ["-ar", str(audio["sample_rate"])]
    norm = audio.get("loudnorm")
    if norm:
        args += ["-af", f"loudnorm=I={norm['I']}:TP={norm['TP']}:LRA={norm['LRA']}"]
    return args


# H.264 SEI (NAL type 6) carries user data such as the encoder's name, build and
# settings string. Dropping it also drops in-band captions and recovery-point hints.
SEI_FILTER = {"h264": "filter_units=remove_types=6"}


def _output_video_codec(preset, source_video_codec):
    video = preset.get("video") or {}
    if preset.get("reencode"):
        return {"libx264": "h264"}.get(video.get("codec"), video.get("codec"))
    return source_video_codec


def build_command(input_path, output_path, preset, ffmpeg="ffmpeg", progress=True, source_video_codec=None):
    container = preset.get("container", "source")
    target = container if container != "source" else os.path.splitext(output_path)[1].lstrip(".").lower()
    reencode = bool(preset.get("reencode"))
    keep_subs = bool(preset.get("keep_subtitles"))

    args = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", input_path,
            # Keep only the real content streams: drops data, timecode and attachment streams.
            "-map", "0:v?", "-map", "0:a?"]
    if keep_subs:
        args += ["-map", "0:s?"]
    # Drop global + per-stream tags and chapter markers; bitexact stops ffmpeg
    # writing its own version string into the container.
    args += ["-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact"]

    if reencode:
        video, audio = preset.get("video"), preset.get("audio")
        if video:
            args += _video_args(video) + ["-flags:v", "+bitexact"]
        else:
            args += ["-vn"]
        if audio:
            args += _audio_args(audio) + ["-flags:a", "+bitexact"]
        else:
            args += ["-an"]
    else:
        args += ["-c:v", "copy", "-c:a", "copy"]

    bsf = SEI_FILTER.get(_output_video_codec(preset, source_video_codec))
    if preset.get("strip_encoder_info", True) and bsf:
        args += ["-bsf:v", bsf]
    if keep_subs:
        args += ["-c:s", "mov_text" if target in ("mp4", "m4v", "mov") else "copy"]
    if preset.get("faststart") and target in ("mp4", "m4v", "mov", "m4a"):
        args += ["-movflags", "+faststart"]
    if target == "mp3":  # the mp3 muxer writes an (empty) ID3v2 header by default
        args += ["-id3v2_version", "0", "-write_id3v1", "0"]
    if progress:
        args += ["-progress", "pipe:1", "-nostats"]
    args.append(output_path)
    return args
