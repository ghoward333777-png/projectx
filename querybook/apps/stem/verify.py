"""Re-check deterministic facts by computing them again.

Used for (1) facts imported from the old QueryBook store and (2) facts saved in this app.
A fact is kept as 'verified' only when the recomputed answer equals the stored one.
"""
import math, re

import engine
import science
import units

MONTH_DAYS = {"january": 31, "february": 28, "march": 31, "april": 30, "may": 31, "june": 30, "july": 31,
              "august": 31, "september": 30, "october": 31, "november": 30, "december": 31}

# Old-store predicates this app understands (everything else is left for the History & News app).
OLD_DOMAINS = ("mathematics", "arithmetic", "geometry", "history", "culture", "art")
RULE_PREDICATES = {"equals", "area", "circumference", "perimeter", "in_century", "in_decade", "is_leap_year",
                   "days_in_common_year", "hex"}


def is_leap(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def check_old(rec):
    """Return (question, expected_answer) for a deterministic old-store record, or None if it is not one."""
    s, p, o, dom = rec["subject"], rec["predicate"], rec["object"], rec["domain"]
    if p not in RULE_PREDICATES or dom not in OLD_DOMAINS:
        return None
    if p == "equals":
        try:
            r = engine.evaluate(s)
        except engine.CalcError:
            return None
        return s, r["value"]
    m = re.fullmatch(r"circle radius (\d+(?:\.\d+)?)", s)
    if m and p in ("area", "circumference"):
        r = float(m.group(1))
        v = math.pi * r * r if p == "area" else 2 * math.pi * r
        return "%s of a circle of radius %s" % (p, m.group(1)), "%s" % round(v, 4)
    m = re.fullmatch(r"square side (\d+(?:\.\d+)?)", s)
    if m and p in ("area", "perimeter"):
        a = engine.evaluate(m.group(1))["value"]
        from fractions import Fraction
        v = Fraction(a) ** 2 if p == "area" else 4 * Fraction(a)
        return "%s of a square of side %s" % (p, m.group(1)), engine.describe(v)["value"]
    m = re.fullmatch(r"year (\d+)", s)
    if m and p in ("in_century", "in_decade", "is_leap_year"):
        y = int(m.group(1))
        if p == "in_century":
            return "century of the year %d" % y, str((y - 1) // 100 + 1)
        if p == "in_decade":
            return "decade of the year %d" % y, "%ds" % ((y // 10) * 10)
        return "is %d a leap year (Gregorian rule)" % y, "yes" if is_leap(y) else "no"
    if p == "days_in_common_year" and s.lower() in MONTH_DAYS:
        return "days in %s in a common year" % s, str(MONTH_DAYS[s.lower()])
    m = re.fullmatch(r"grayscale level (\d+)", s)
    if m and p == "hex":
        v = int(m.group(1))
        if 0 <= v <= 255:
            return "hex colour of grayscale level %d" % v, "#%02x%02x%02x" % (v, v, v)
    return None


def answers_match(stored, expected):
    if engine.same_value(stored, expected):
        return True
    try:  # geometry facts were stored rounded to 4 places
        return round(float(str(stored).replace(",", "")), 4) == round(float(str(expected).replace(",", "")), 4)
    except ValueError:
        return engine.norm_text(stored) == engine.norm_text(expected)


def recompute(kind, question, detail):
    """Recompute a saved fact. Returns the answer string, or raises."""
    if kind == "calc":
        return engine.evaluate(question)["value"]
    if kind == "convert":
        return units.convert(question)["result"]
    if kind == "molar":
        return science.molar_mass(question)["molar_mass"]
    if kind == "formula":
        r = science.solve(detail["id"], detail["unknown"], detail["given"])
        return r["result"]["value"]
    if kind == "imported":
        got = check_old(detail)
        if got is None:
            raise ValueError("no longer recognised as a deterministic fact")
        return got[1]
    raise ValueError("unknown kind")
