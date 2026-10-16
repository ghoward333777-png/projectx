"""Historical dates as people write them -> a sortable key, a precision and a clean label.

Accepted: 1215 · 1215-06-15 · 15 June 1215 · June 15, 1215 · June 1215 · 44 BC · 44 BCE · 15 March 44 BC
          c. 1200 · circa 1200 · 1990s · 12th century · 3rd century BC · 2026-10-16
Sort key: year*10000 + month*100 + day (BC years are negative; there is no year 0).
"""
import re

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9
MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
DAYS_IN = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


class DateError(Exception):
    pass


def _ord(n):
    return "%d%s" % (n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def parse(text):
    """Return {"sort": int, "precision": str, "label": str, "year": int, "month": int|None, "day": int|None, "approx": bool}
    or None for an empty input. Raises DateError for text that is not a date."""
    raw = str(text or "").strip()
    if not raw:
        return None
    s = raw.lower().replace(",", " ").replace(".", " ").strip()
    approx = False
    m = re.match(r"^(c|ca|circa|about|around|approx)\s+(.*)$", s)
    if m:
        approx, s = True, m.group(2).strip()
    era = 1
    m = re.match(r"^(.*?)\s*(bc|bce|b c|b c e)$", s)
    if m:
        era, s = -1, m.group(1).strip()
    else:
        m = re.match(r"^(.*?)\s*(ad|ce|a d)$", s) or re.match(r"^(ad|a d)\s+(.*)$", s)
        if m:
            s = (m.group(1) if m.group(1) not in ("ad", "a d") else m.group(2)).strip()
    s = " ".join(s.split())
    m = re.match(r"^(\d{1,2})(st|nd|rd|th)\s+century$", s)
    if m:
        c = int(m.group(1))
        y = (c - 1) * 100 + 1 if era > 0 else -(c * 100)
        label = "%s century%s" % (_ord(c), " BC" if era < 0 else "")
        return _out(y, None, None, "century", label, approx)
    m = re.match(r"^(\d{3,4})s$", s)
    if m:
        y = int(m.group(1))
        return _out(y * era, None, None, "decade", "%ds%s" % (y, " BC" if era < 0 else ""), approx)
    m = re.match(r"^(-?\d{1,4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        return _ymd(int(m.group(1)) * era, int(m.group(2)), int(m.group(3)), approx)
    m = re.match(r"^(-?\d{1,4})-(\d{1,2})$", s)
    if m:
        return _ymd(int(m.group(1)) * era, int(m.group(2)), None, approx)
    m = re.match(r"^(\d{1,2})\s+([a-z]+)\s+(\d{1,4})$", s)            # 15 june 1215
    if m and m.group(2) in MONTHS:
        return _ymd(int(m.group(3)) * era, MONTHS[m.group(2)], int(m.group(1)), approx)
    m = re.match(r"^([a-z]+)\s+(\d{1,2})(st|nd|rd|th)?\s+(\d{1,4})$", s)   # june 15 1215
    if m and m.group(1) in MONTHS:
        return _ymd(int(m.group(4)) * era, MONTHS[m.group(1)], int(m.group(2)), approx)
    m = re.match(r"^([a-z]+)\s+(\d{1,4})$", s)                         # june 1215
    if m and m.group(1) in MONTHS:
        return _ymd(int(m.group(2)) * era, MONTHS[m.group(1)], None, approx)
    m = re.match(r"^(-?\d{1,4})$", s)
    if m:
        return _ymd(int(m.group(1)) * era, None, None, approx)
    raise DateError("'%s' is not a date I can read — try 1215, 15 June 1215, 44 BC, 1990s or 12th century" % raw)


def _ymd(y, mo, d, approx):
    if y == 0:
        raise DateError("there is no year 0 — use 1 BC or AD 1")
    if mo is not None and not 1 <= mo <= 12:
        raise DateError("month must be 1–12")
    if d is not None and not 1 <= d <= DAYS_IN[mo]:
        raise DateError("%s has no day %d" % (MONTH_NAMES[mo], d))
    leap = (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) if y >= 1583 else (abs(y) % 4 == 0)   # Gregorian from 1583, Julian before
    if mo == 2 and d == 29 and not leap:
        raise DateError("%s was not a leap year" % (("%d BC" % -y) if y < 0 else y))
    ystr = "%d BC" % -y if y < 0 else str(y)
    if d:
        label, prec = "%d %s %s" % (d, MONTH_NAMES[mo], ystr), "day"
    elif mo:
        label, prec = "%s %s" % (MONTH_NAMES[mo], ystr), "month"
    else:
        label, prec = ystr, "year"
    return _out(y, mo, d, prec, label, approx)


def _out(y, mo, d, prec, label, approx):
    sort = y * 10000 + (mo or 0) * 100 + (d or 0) if y > 0 else y * 10000 - (13 - (mo or 13)) * 100 - (32 - (d or 32))
    return {"sort": sort, "precision": prec, "label": ("c. " if approx else "") + label, "year": y, "month": mo, "day": d, "approx": approx}
