"""Unit conversion with dimensional analysis. Exact conversion factors where the definition is exact.

Every unit is a scale factor to SI plus a dimension vector over (m, kg, s, A, K, mol, cd).
Compound units are built by the parser: "km/h", "kg*m/s^2", "N·m", "m^3", "W/(m^2*K)".
Temperatures with an offset (°C, °F) convert only on their own, e.g. "100 degF to degC".
Sources of the definitions: SI Brochure (9th ed., 2019) and NIST SP 811 (exact factors).
"""
import re
from fractions import Fraction as F

DIMS = ("m", "kg", "s", "A", "K", "mol", "cd")


def _d(**k):
    return tuple(k.get(n, 0) for n in DIMS)


L, M, T, I, TH, N, J = (_d(m=1), _d(kg=1), _d(s=1), _d(A=1), _d(K=1), _d(mol=1), _d(cd=1))
NONE = _d()


def _mul(a, b, k=1):
    return tuple(x + k * y for x, y in zip(a, b))


def _pow(a, n):
    return tuple(x * n for x in a)


VEL = _mul(L, T, -1)
ACC = _mul(VEL, T, -1)
FORCE = _mul(M, ACC)
ENERGY = _mul(FORCE, L)
POWER = _mul(ENERGY, T, -1)
PRESS = _mul(FORCE, _pow(L, -2))
CHARGE = _mul(I, T)
VOLT = _mul(POWER, I, -1)
OHM = _mul(VOLT, I, -1)
FREQ = _pow(T, -1)
AREA = _pow(L, 2)
VOL = _pow(L, 3)

# name: (factor to SI, dimension, description)
UNITS = {
    # length
    "m": (F(1), L, "metre"), "km": (F(1000), L, "kilometre"), "cm": (F(1, 100), L, "centimetre"), "mm": (F(1, 1000), L, "millimetre"),
    "um": (F(1, 10**6), L, "micrometre"), "µm": (F(1, 10**6), L, "micrometre"), "nm": (F(1, 10**9), L, "nanometre"),
    "in": (F(254, 10000), L, "inch (exactly 2.54 cm)"), "ft": (F(3048, 10000), L, "foot (exactly 0.3048 m)"),
    "yd": (F(9144, 10000), L, "yard (exactly 0.9144 m)"), "mi": (F(1609344, 1000), L, "mile (exactly 1609.344 m)"),
    "nmi": (F(1852), L, "nautical mile (exactly 1852 m)"), "au": (F(149597870700), L, "astronomical unit (exact)"),
    "ly": (F(9460730472580800), L, "light-year (Julian year × c, exact)"), "angstrom": (F(1, 10**10), L, "ångström"),
    # mass
    "kg": (F(1), M, "kilogram"), "g": (F(1, 1000), M, "gram"), "mg": (F(1, 10**6), M, "milligram"), "ug": (F(1, 10**9), M, "microgram"),
    "t": (F(1000), M, "tonne"), "lb": (F(45359237, 10**8), M, "pound (exactly 0.45359237 kg)"),
    "oz": (F(45359237, 16 * 10**8), M, "ounce (1/16 lb)"), "st": (F(14 * 45359237, 10**8), M, "stone (14 lb)"),
    "ton": (F(2000 * 45359237, 10**8), M, "short ton (2000 lb)"), "u": (F("1.66053906660e-27"), M, "atomic mass unit (CODATA 2018)"),
    # time
    "s": (F(1), T, "second"), "ms": (F(1, 1000), T, "millisecond"), "us": (F(1, 10**6), T, "microsecond"), "ns": (F(1, 10**9), T, "nanosecond"),
    "min": (F(60), T, "minute"), "h": (F(3600), T, "hour"), "hr": (F(3600), T, "hour"), "day": (F(86400), T, "day"),
    "week": (F(604800), T, "week"), "yr": (F(31557600), T, "Julian year (365.25 days)"), "year": (F(31557600), T, "Julian year (365.25 days)"),
    # area and volume
    "ha": (F(10000), AREA, "hectare"), "acre": (F(40468564224, 10**7), AREA, "international acre"),
    "L": (F(1, 1000), VOL, "litre"), "l": (F(1, 1000), VOL, "litre"), "mL": (F(1, 10**6), VOL, "millilitre"), "ml": (F(1, 10**6), VOL, "millilitre"),
    "gal": (F(3785411784, 10**12), VOL, "US gallon (exactly 3.785411784 L)"), "qt": (F(3785411784, 4 * 10**12), VOL, "US quart"),
    "pt": (F(3785411784, 8 * 10**12), VOL, "US pint"), "floz": (F(3785411784, 128 * 10**12), VOL, "US fluid ounce"),
    "impgal": (F(454609, 10**8), VOL, "imperial gallon (exactly 4.54609 L)"),
    # speed
    "mph": (F(1609344, 3600 * 1000), VEL, "mile per hour"), "kph": (F(1000, 3600), VEL, "kilometre per hour"),
    "knot": (F(1852, 3600), VEL, "knot (nautical mile per hour)"), "kn": (F(1852, 3600), VEL, "knot"),
    # force, energy, power
    "N": (F(1), FORCE, "newton"), "kN": (F(1000), FORCE, "kilonewton"), "dyn": (F(1, 10**5), FORCE, "dyne"),
    "lbf": (F(45359237 * 980665, 10**8 * 10**5), FORCE, "pound-force"), "kgf": (F(980665, 10**5), FORCE, "kilogram-force"),
    "J": (F(1), ENERGY, "joule"), "kJ": (F(1000), ENERGY, "kilojoule"), "MJ": (F(10**6), ENERGY, "megajoule"),
    "cal": (F(4184, 1000), ENERGY, "thermochemical calorie (exactly 4.184 J)"), "kcal": (F(4184), ENERGY, "kilocalorie"),
    "Wh": (F(3600), ENERGY, "watt-hour"), "kWh": (F(3600000), ENERGY, "kilowatt-hour"),
    "eV": (F("1.602176634e-19"), ENERGY, "electronvolt (exact)"), "BTU": (F("1055.05585262"), ENERGY, "BTU (International Table)"),
    "W": (F(1), POWER, "watt"), "kW": (F(1000), POWER, "kilowatt"), "MW": (F(10**6), POWER, "megawatt"),
    "hp": (F("745.69987158227022"), POWER, "mechanical horsepower"),
    # pressure
    "Pa": (F(1), PRESS, "pascal"), "kPa": (F(1000), PRESS, "kilopascal"), "MPa": (F(10**6), PRESS, "megapascal"),
    "bar": (F(10**5), PRESS, "bar"), "mbar": (F(100), PRESS, "millibar"), "atm": (F(101325), PRESS, "standard atmosphere (exact)"),
    "psi": (F(45359237 * 980665, 10**8 * 10**5) / F(254, 10000) ** 2, PRESS, "pound-force per square inch"),
    "mmHg": (F("133.322387415"), PRESS, "millimetre of mercury"), "torr": (F(101325, 760), PRESS, "torr (1/760 atm)"),
    # electricity, frequency, amount, light
    "A": (F(1), I, "ampere"), "mA": (F(1, 1000), I, "milliampere"), "C": (F(1), CHARGE, "coulomb"), "mAh": (F(36, 10), CHARGE, "milliampere-hour"),
    "Ah": (F(3600), CHARGE, "ampere-hour"), "V": (F(1), VOLT, "volt"), "mV": (F(1, 1000), VOLT, "millivolt"), "kV": (F(1000), VOLT, "kilovolt"),
    "ohm": (F(1), OHM, "ohm"), "Ω": (F(1), OHM, "ohm"), "kohm": (F(1000), OHM, "kilohm"), "Mohm": (F(10**6), OHM, "megohm"),
    "Hz": (F(1), FREQ, "hertz"), "kHz": (F(1000), FREQ, "kilohertz"), "MHz": (F(10**6), FREQ, "megahertz"), "GHz": (F(10**9), FREQ, "gigahertz"),
    "rpm": (F(1, 60), FREQ, "revolution per minute"), "mol": (F(1), N, "mole"), "mmol": (F(1, 1000), N, "millimole"), "cd": (F(1), J, "candela"),
    "K": (F(1), TH, "kelvin"),
    # dimensionless
    "rad": (F(1), NONE, "radian"), "percent": (F(1, 100), NONE, "percent"),
}
ALIASES = {"meter": "m", "metre": "m", "meters": "m", "metres": "m", "kilometer": "km", "kilometers": "km", "kilometre": "km",
           "kilometres": "km", "centimeter": "cm", "centimeters": "cm", "millimeter": "mm", "millimeters": "mm", "inch": "in",
           "inches": "in", "foot": "ft", "feet": "ft", "yard": "yd", "yards": "yd", "mile": "mi", "miles": "mi",
           "gram": "g", "grams": "g", "kilogram": "kg", "kilograms": "kg", "kilo": "kg", "kilos": "kg", "pound": "lb", "pounds": "lb", "lbs": "lb",
           "ounce": "oz", "ounces": "oz", "tonne": "t", "tonnes": "t", "second": "s", "seconds": "s", "sec": "s", "minute": "min",
           "minutes": "min", "hour": "h", "hours": "h", "days": "day", "weeks": "week", "years": "year", "liter": "L", "liters": "L",
           "litre": "L", "litres": "L", "gallon": "gal", "gallons": "gal", "knots": "knot", "newton": "N", "newtons": "N", "joule": "J",
           "joules": "J", "calorie": "cal", "calories": "cal", "watt": "W", "watts": "W", "kilowatt": "kW", "horsepower": "hp",
           "pascal": "Pa", "volt": "V", "volts": "V", "amp": "A", "amps": "A", "ampere": "A", "hertz": "Hz", "kelvin": "K",
           "mole": "mol", "moles": "mol", "km/h": "kph", "kmh": "kph", "deg": "degree", "degrees": "degree", "°": "degree"}
UNITS["degree"] = (F(1), NONE, "degree of angle (converted with π/180 when mixed with rad)")
TEMPS = {"degC": ("°C", F(1), F("273.15")), "°C": ("°C", F(1), F("273.15")), "C°": ("°C", F(1), F("273.15")), "celsius": ("°C", F(1), F("273.15")),
         "degF": ("°F", F(5, 9), F("459.67") * F(5, 9)), "°F": ("°F", F(5, 9), F("459.67") * F(5, 9)), "fahrenheit": ("°F", F(5, 9), F("459.67") * F(5, 9)),
         "degR": ("°R", F(5, 9), F(0)), "rankine": ("°R", F(5, 9), F(0)), "K": ("K", F(1), F(0)), "kelvin": ("K", F(1), F(0))}


class UnitError(Exception):
    pass


def _one(name):
    n = ALIASES.get(name, ALIASES.get(name.lower(), name))
    if n in UNITS:
        return UNITS[n][0], UNITS[n][1]
    if n.lower() in UNITS and n.lower() not in ("t",):
        return UNITS[n.lower()][0], UNITS[n.lower()][1]
    raise UnitError("unknown unit '%s'" % name)


def parse_unit(text):
    """'kg*m/s^2' -> (factor, dims). Supports * · / ^ and parentheses one level deep."""
    s = text.strip().replace("·", "*").replace("×", "*").replace("²", "^2").replace("³", "^3").replace(" per ", "/")
    if not s:
        return F(1), NONE
    if s in ALIASES and "/" in s:
        s = ALIASES[s]
    tokens = re.findall(r"\(|\)|\*|/|\^-?\d+|[^\s*/()^]+", s)
    # Grammar: factor (('*' | '/') factor)* ; factor = name ['^' n] | '(' units ')' ['^' n].
    # A '/' divides by the next factor only: kg*m/s^2 = kg·m·s⁻²; W/(m^2*K) needs the brackets.
    pos = [0]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def take():
        t = peek()
        pos[0] += 1
        return t

    def factor():
        t = take()
        if t is None:
            raise UnitError("incomplete unit")
        if t == "(":
            f, d = product()
            if take() != ")":
                raise UnitError("unbalanced brackets in unit")
        elif t in (")", "*", "/") or t.startswith("^"):
            raise UnitError("misplaced '%s' in unit" % t)
        else:
            f, d = _one(t)
        if peek() and peek().startswith("^"):
            p = int(take()[1:])
            f, d = f ** p, _pow(d, p)
        return f, d

    def product():
        f, d = factor()
        while peek() in ("*", "/"):
            op = take()
            g, e = factor()
            if op == "*":
                f, d = f * g, _mul(d, e)
            else:
                f, d = f / g, _mul(d, e, -1)
        return f, d

    factor_, dims_ = product()
    if pos[0] != len(tokens):
        raise UnitError("could not read the unit '%s'" % text)
    factor, dims = factor_, dims_
    return factor, dims


def dim_string(d):
    parts = []
    for name, p in zip(DIMS, d):
        if p:
            parts.append(name if p == 1 else "%s^%d" % (name, p))
    return "·".join(parts) or "dimensionless"


_Q = re.compile(r"^\s*(?:convert\s+)?([-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*(.+?)\s+(?:to|in|into|as)\s+(.+?)\s*\??$", re.I)


def convert(text):
    """'5 km/h to m/s' -> result dict. Raises UnitError with a plain message."""
    m = _Q.match(text or "")
    if not m:
        raise UnitError("write it like: 5 km to mi   or   100 degF to degC")
    value = F(m.group(1).replace(",", ""))
    src, dst = m.group(2).strip(), m.group(3).strip()
    return convert_value(value, src, dst)


def convert_value(value, src, dst):
    value = F(value)
    ts, td = TEMPS.get(src) or TEMPS.get(src.lower()), TEMPS.get(dst) or TEMPS.get(dst.lower())
    if src in ("°", "degree") or dst in ("°", "degree"):
        ts = td = None
    if (ts and td) and not (src == "K" and dst == "K"):
        kelvin = value * ts[1] + ts[2]
        out = (kelvin - td[2]) / td[1]
        return _result(value, ts[0], out, td[0], "temperature (offset scale)")
    fs, ds = parse_unit(src)
    fd, dd = parse_unit(dst)
    if src.lower() in ("degree", "deg", "degrees", "°") and dst == "rad":
        fs = F(1)
        out = None
        import math
        return _result(value, src, None, dst, "angle", approx=float(value) * math.pi / 180)
    if dst.lower() in ("degree", "deg", "degrees", "°") and src == "rad":
        import math
        return _result(value, src, None, dst, "angle", approx=float(value) * 180 / math.pi)
    if ds != dd:
        raise UnitError("cannot convert %s (%s) to %s (%s) — the dimensions differ" % (src, dim_string(ds), dst, dim_string(dd)))
    out = value * fs / fd
    return _result(value, src, out, dst, dim_string(ds))


def to_si(value_with_unit, expected_dims=None):
    """'60 mph' -> (Fraction in SI, dims). A bare number is taken as SI."""
    s = str(value_with_unit).strip()
    m = re.match(r"^([-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*(.*)$", s)
    if not m:
        raise UnitError("'%s' is not a number" % s)
    v = F(m.group(1).replace(",", ""))
    u = m.group(2).strip()
    if not u:
        return v, expected_dims
    t = TEMPS.get(u) or TEMPS.get(u.lower())
    if t and u not in ("K",):
        return v * t[1] + t[2], TH
    f, d = parse_unit(u)
    if expected_dims is not None and d != expected_dims:
        raise UnitError("'%s' has the wrong kind of unit (%s; expected %s)" % (s, dim_string(d), dim_string(expected_dims)))
    return v * f, d


def _fmt(fr):
    if fr is None:
        return None
    if fr.denominator == 1:
        return str(fr.numerator)
    if _terminates(fr):
        import decimal
        with decimal.localcontext() as ctx:
            ctx.prec = 60
            d = (decimal.Decimal(fr.numerator) / decimal.Decimal(fr.denominator)).normalize()
        if d != 0 and (abs(d) < decimal.Decimal("1e-6") or abs(d) >= decimal.Decimal("1e15")):
            return format(d, "e").replace("e", "e").replace("E", "e")
        txt = format(d, "f")
        if len(txt.replace("-", "").replace(".", "").lstrip("0")) <= 24:
            return txt
    x = float(fr)
    if abs(x) >= 1e15 or (abs(x) < 1e-6 and x != 0):
        return "%.12g" % x
    return ("%.12f" % x).rstrip("0").rstrip(".")


def _result(value, src, out, dst, kind, approx=None):
    exact = out is not None and (out.denominator == 1 or _terminates(out))
    disp = _fmt(out) if out is not None else ("%.12g" % approx)
    return {"input": "%s %s" % (_fmt(value), src), "result": disp, "unit": dst, "kind": kind,
            "exact": bool(exact), "display": "%s %s = %s%s %s" % (_fmt(value), src, "" if exact else "≈ ", disp, dst)}


def _terminates(fr):
    d = fr.denominator
    for p in (2, 5):
        while d % p == 0:
            d //= p
    return d == 1


def unit_table():
    out = []
    for k, (f, d, desc) in UNITS.items():
        out.append({"unit": k, "description": desc, "dimension": dim_string(d), "si_factor": _fmt(f)})
    for k, (sym, a, b) in TEMPS.items():
        if k in ("degC", "degF", "degR"):
            out.append({"unit": k, "description": "temperature %s (offset scale; converts on its own)" % sym, "dimension": "K", "si_factor": "affine"})
    return out
