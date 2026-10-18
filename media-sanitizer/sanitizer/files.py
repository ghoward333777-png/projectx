"""Expanding user-supplied paths into media files, with optional root restrictions."""

import os
import re


def check_allowed(path, settings):
    roots = settings.get("allowed_input_roots") or []
    real = os.path.realpath(path)
    allowed = [os.path.realpath(r) for r in roots] + [os.path.realpath(settings["workspace"])]
    if roots and not any(real == r or real.startswith(r + os.sep) for r in allowed):
        raise PermissionError(f"{path} is outside allowed_input_roots")
    return real


def collect_media(paths, settings, recursive=True):
    """Files and folders in, sorted list of media file paths out."""
    exts = tuple(settings["media_extensions"])
    found = []
    for p in paths:
        p = check_allowed(os.path.expanduser(p), settings)
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs.sort()
                found += [os.path.join(root, f) for f in sorted(files) if f.lower().endswith(exts)]
                if not recursive:
                    break
        elif os.path.isfile(p) and p.lower().endswith(exts):
            found.append(p)
        elif not os.path.exists(p):
            raise FileNotFoundError(p)
    return list(dict.fromkeys(found))


def safe_filename(name):
    """Upload names: basename only, conservative characters."""
    base = os.path.basename(name.replace("\\", "/")).strip() or "upload"
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).lstrip(".")
    return base[:150] or "upload"
