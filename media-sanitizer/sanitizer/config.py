"""Loading and validation of the JSON configuration files."""

import json
import os

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(APP_ROOT, "config")

CONTAINERS = {"mp4", "mov", "mkv", "source"}
VIDEO_CODECS = {"libx264", "libx265", "ffv1", "prores_ks", "copy"}
AUDIO_CODECS = {"aac", "libopus", "flac", "pcm_s16le", "pcm_s24le", "libmp3lame", "copy"}
# Codecs each container can hold; "source" (stream copy) is not checked.
CONTAINER_CODECS = {
    "mp4": {"libx264", "libx265", "aac", "libopus", "flac", "libmp3lame", "copy"},
    "mov": VIDEO_CODECS | AUDIO_CODECS,
    "mkv": VIDEO_CODECS | AUDIO_CODECS,
}


class ConfigError(ValueError):
    pass


def _read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{os.path.basename(path)}: invalid JSON ({exc})") from exc


def load_settings(path=None):
    settings = _read_json(path or os.path.join(CONFIG_DIR, "settings.json"))
    for key in ("workspace", "default_output_dir"):
        if not os.path.isabs(settings[key]):
            settings[key] = os.path.join(APP_ROOT, settings[key])
    settings["media_extensions"] = [e.lower() for e in settings["media_extensions"]]
    settings["technical_tags"] = [t.lower() for t in settings["technical_tags"]]
    return settings


def validate_preset(name, preset):
    """Return a list of problems with one preset definition (empty when valid)."""
    errors = []
    if not isinstance(preset, dict):
        return [f"{name}: preset must be an object"]
    if not preset.get("description"):
        errors.append(f"{name}: missing description")
    container = preset.get("container")
    if container not in CONTAINERS:
        errors.append(f"{name}: container must be one of {sorted(CONTAINERS)}")
    if not preset.get("reencode"):
        return errors
    if container == "source":
        errors.append(f"{name}: re-encoding presets need an explicit container")
    video, audio = preset.get("video"), preset.get("audio")
    if not video and not audio:
        errors.append(f"{name}: re-encoding presets need a video and/or audio section")
    for kind, section, allowed in (("video", video, VIDEO_CODECS), ("audio", audio, AUDIO_CODECS)):
        if section is None:
            continue
        codec = section.get("codec")
        if codec not in allowed:
            errors.append(f"{name}: {kind} codec '{codec}' not in {sorted(allowed)}")
        elif container in CONTAINER_CODECS and codec not in CONTAINER_CODECS[container]:
            errors.append(f"{name}: {kind} codec '{codec}' cannot go in {container}")
    if video and "crf" in video and not (0 <= int(video["crf"]) <= 51):
        errors.append(f"{name}: crf must be 0-51")
    loudnorm = (audio or {}).get("loudnorm")
    if loudnorm is not None and not {"I", "TP", "LRA"} <= set(loudnorm):
        errors.append(f"{name}: loudnorm needs I, TP and LRA")
    return errors


def load_presets(path=None):
    presets = _read_json(path or os.path.join(CONFIG_DIR, "presets.json"))
    if not isinstance(presets, dict) or not presets:
        raise ConfigError("presets.json must be a non-empty object")
    errors = [e for name, p in presets.items() for e in validate_preset(name, p)]
    if errors:
        raise ConfigError("; ".join(errors))
    return presets
