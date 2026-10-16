"""Deterministic calculation engine: exact arithmetic, safe expression evaluation, number theory.

Nothing here guesses. Integers and fractions stay exact; 0.1 is read as exactly 1/10.
Irrational results (square roots of non-squares, trigonometry, logarithms) are computed
in floating point and labelled as approximate. Expressions are parsed with Python's `ast`
module and only whitelisted operations are allowed — nothing is ever passed to eval().
"""
import ast, math, re
from fractions import Fraction

MAX_DIGITS = 5000          # largest exact result shown in full
MAX_EXPONENT = 100000      # largest integer exponent accepted


class CalcError(Exception):
    pass


class Approx(float):
    """A float result that is known to be approximate."""


# ----------------------------------------------------------------------------- number theory
_SMALL_PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]


def is_prime(n):
    """Deterministic Miller–Rabin. Exact for n < 3.317e24 (bases up to 41);
    above that the answer is 'probable prime' and is reported as such."""
    n = int(n)
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for a in _SMALL_PRIMES:
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


PRIME_CERTAIN_BELOW = 3317044064679887385961981


def _pollard_rho(n):
    if n % 2 == 0:
        return 2
    for c in range(1, 200):
        x = y = 2
        d = 1
        f = lambda v: (v * v + c) % n
        while d == 1:
            x = f(x)
            y = f(f(y))
            d = math.gcd(abs(x - y), n)
        if d != n:
            return d
    raise CalcError("could not factor this number in reasonable time")


def factorize(n):
    """Prime factorization as {prime: exponent}. Deterministic."""
    n = int(n)
    if n == 0:
        raise CalcError("0 has no prime factorization")
    out = {}
    if n < 0:
        out[-1] = 1
        n = -n
    for p in [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]:
        while n % p == 0:
            out[p] = out.get(p, 0) + 1
            n //= p
    stack = [n] if n > 1 else []
    while stack:
        m = stack.pop()
        if m == 1:
            continue
        if is_prime(m):
            out[m] = out.get(m, 0) + 1
            continue
        if m.bit_length() > 200:
            raise CalcError("number too large to factor here")
        d = _pollard_rho(m)
        stack += [d, m // d]
    return dict(sorted(out.items()))


def factor_string(n):
    f = factorize(n)
    sup = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
    return " × ".join(str(p) + (str(e).translate(sup) if e > 1 else "") for p, e in f.items())


# ----------------------------------------------------------------------------- exact helpers
def _exact(v):
    return isinstance(v, (int, Fraction)) and not isinstance(v, bool)


def _to_frac(v):
    if isinstance(v, Fraction):
        return v
    if isinstance(v, int):
        return Fraction(v)
    raise TypeError


def _isqrt_exact(fr):
    """Exact square root of a non-negative Fraction when it is a perfect square, else None."""
    if fr < 0:
        return None
    a, b = fr.numerator, fr.denominator
    ra, rb = math.isqrt(a), math.isqrt(b)
    if ra * ra == a and rb * rb == b:
        return Fraction(ra, rb)
    return None


def _iroot_exact(fr, k):
    if fr < 0 and k % 2 == 1:
        r = _iroot_exact(-fr, k)
        return -r if r is not None else None
    if fr < 0:
        return None
    def iroot(n):
        x = round(n ** (1.0 / k)) if n < 2 ** 1000 else int(math.exp(math.log(n) / k))
        for c in (x - 1, x, x + 1):
            if c >= 0 and c ** k == n:
                return c
        return None
    a, b = iroot(fr.numerator), iroot(fr.denominator)
    return Fraction(a, b) if a is not None and b is not None else None


def _f(v):
    return float(v)


def _approx(x):
    if isinstance(x, complex) or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        raise CalcError("the result is not a real number")
    return Approx(x)


# ----------------------------------------------------------------------------- functions
def _sqrt(x):
    if _exact(x):
        r = _isqrt_exact(_to_frac(x))
        if r is not None:
            return r
    if x < 0:
        raise CalcError("square root of a negative number is not a real number")
    return _approx(math.sqrt(_f(x)))


def _cbrt(x):
    if _exact(x):
        r = _iroot_exact(_to_frac(x), 3)
        if r is not None:
            return r
    v = _f(x)
    return _approx(math.copysign(abs(v) ** (1 / 3), v))


def _root(x, k):
    k = _int_arg(k, "root degree")
    if k < 1:
        raise CalcError("root degree must be at least 1")
    if _exact(x):
        r = _iroot_exact(_to_frac(x), k)
        if r is not None:
            return r
    v = _f(x)
    if v < 0 and k % 2 == 0:
        raise CalcError("even root of a negative number is not a real number")
    return _approx(math.copysign(abs(v) ** (1 / k), v))


def _int_arg(x, what="argument"):
    if isinstance(x, Fraction) and x.denominator == 1:
        return int(x)
    if isinstance(x, int) and not isinstance(x, bool):
        return x
    raise CalcError("%s must be a whole number" % what)


def _factorial(x):
    n = _int_arg(x, "factorial argument")
    if n < 0:
        raise CalcError("factorial is defined for 0 and positive whole numbers")
    if n > 3000:
        raise CalcError("factorial argument too large (limit 3000)")
    return math.factorial(n)


def _log(x, base=None):
    if _f(x) <= 0:
        raise CalcError("logarithm is defined for positive numbers only")
    if base is None:
        return _approx(math.log10(_f(x)))
    if _exact(x) and _exact(base):
        # exact when x is an integer power of base
        bx, bb = _to_frac(x), _to_frac(base)
        if bb > 0 and bb != 1:
            k = round(math.log(_f(bx)) / math.log(_f(bb)))
            if abs(k) < 4000 and bb ** k == bx:
                return k
    if _f(base) <= 0 or _f(base) == 1:
        raise CalcError("logarithm base must be positive and not 1")
    return _approx(math.log(_f(x)) / math.log(_f(base)))


def _trig(fn, degrees=False):
    def g(x):
        v = _f(x)
        if degrees:
            exact = {0: 0, 30: 1, 45: None, 60: None, 90: None}
            k = v % 360
            # exact values at multiples of 90 degrees for sin/cos/tan
            if fn in (math.sin, math.cos) and k % 90 == 0:
                q = int(k // 90)
                return [0, 1, 0, -1][q] if fn is math.sin else [1, 0, -1, 0][q]
            if fn is math.sin and k in (30, 150):
                return Fraction(1, 2)
            if fn is math.sin and k in (210, 330):
                return Fraction(-1, 2)
            if fn is math.cos and k in (60, 300):
                return Fraction(1, 2)
            if fn is math.cos and k in (120, 240):
                return Fraction(-1, 2)
            if fn is math.tan and k % 180 == 0:
                return 0
            if fn is math.tan and k % 180 == 90:
                raise CalcError("tangent is undefined at 90° + k·180°")
            if fn is math.tan and k % 180 == 45:
                return 1 if k % 360 in (45, 225) else -1
            del exact
            v = math.radians(v)
        return _approx(fn(v))
    return g


def _inv_trig(fn, degrees=False):
    def g(x):
        v = _f(x)
        if fn in (math.asin, math.acos) and not -1 <= v <= 1:
            raise CalcError("argument must be between −1 and 1")
        r = fn(v)
        return _approx(math.degrees(r) if degrees else r)
    return g


def _round(x, nd=0):
    nd = _int_arg(nd, "number of decimals")
    if _exact(x):
        q = Fraction(10) ** nd
        v = _to_frac(x) * q
        # round half away from zero (school rounding), not banker's rounding
        n = math.floor(abs(v) + Fraction(1, 2))
        n = n if v >= 0 else -n
        r = Fraction(n) / q
        return int(r) if r.denominator == 1 else r
    return _approx(round(_f(x), nd))


def _gcd(*a):
    return math.gcd(*[_int_arg(x) for x in a])


def _lcm(*a):
    out = 1
    for x in a:
        x = _int_arg(x)
        out = abs(out * x) // math.gcd(out, x) if out and x else 0
    return out


def _comb(n, k):
    return math.comb(_int_arg(n), _int_arg(k))


def _perm(n, k):
    return math.perm(_int_arg(n), _int_arg(k))


def _isprime(n):
    n = _int_arg(n)
    if n >= PRIME_CERTAIN_BELOW:
        raise CalcError("primality is certain only below 3.3 × 10²⁴ here")
    return "prime" if is_prime(n) else "not prime"


def _factor(n):
    return factor_string(_int_arg(n))


def _floor(x):
    return math.floor(x) if _exact(x) else math.floor(_f(x))


def _ceil(x):
    return math.ceil(x) if _exact(x) else math.ceil(_f(x))


def _abs(x):
    return abs(x) if _exact(x) else _approx(abs(_f(x)))


def _exp(x):
    if _exact(x) and x == 0:
        return 1
    return _approx(math.exp(_f(x)))


def _ln(x):
    if _exact(x) and x == 1:
        return 0
    if _f(x) <= 0:
        raise CalcError("logarithm is defined for positive numbers only")
    return _approx(math.log(_f(x)))


def _mean(*a):
    if not a:
        raise CalcError("mean needs at least one number")
    if all(_exact(x) for x in a):
        r = sum(_to_frac(x) for x in a) / len(a)
        return int(r) if r.denominator == 1 else r
    return _approx(sum(_f(x) for x in a) / len(a))


def _median(*a):
    if not a:
        raise CalcError("median needs at least one number")
    s = sorted(a, key=_f)
    m = len(s) // 2
    if len(s) % 2:
        return s[m]
    return _mean(s[m - 1], s[m])


FUNCTIONS = {
    "sqrt": _sqrt, "cbrt": _cbrt, "root": _root, "abs": _abs, "round": _round, "floor": _floor, "ceil": _ceil,
    "exp": _exp, "ln": _ln, "log": _log, "log10": lambda x: _log(x, 10), "log2": lambda x: _log(x, 2),
    "sin": _trig(math.sin), "cos": _trig(math.cos), "tan": _trig(math.tan),
    "sind": _trig(math.sin, True), "cosd": _trig(math.cos, True), "tand": _trig(math.tan, True),
    "asin": _inv_trig(math.asin), "acos": _inv_trig(math.acos), "atan": _inv_trig(math.atan),
    "asind": _inv_trig(math.asin, True), "acosd": _inv_trig(math.acos, True), "atand": _inv_trig(math.atan, True),
    "factorial": _factorial, "gcd": _gcd, "lcm": _lcm, "comb": _comb, "ncr": _comb, "perm": _perm, "npr": _perm,
    "isprime": _isprime, "factor": _factor, "min": lambda *a: min(a, key=_f), "max": lambda *a: max(a, key=_f),
    "hypot": lambda *a: _sqrt(sum((x * x if _exact(x) else _f(x) ** 2) for x in a)),
    "deg": lambda x: _approx(math.degrees(_f(x))), "rad": lambda x: _approx(math.radians(_f(x))),
    "mean": _mean, "average": _mean, "median": _median,
}
CONSTANTS = {"pi": _approx(math.pi), "π": _approx(math.pi), "e": _approx(math.e), "tau": _approx(math.tau), "phi": _approx((1 + 5 ** 0.5) / 2)}

FUNCTION_HELP = [
    ("sqrt(x), cbrt(x), root(x, n)", "square, cube and n-th roots (exact when the root is exact)"),
    ("x^n or x**n, n!", "powers and factorials"),
    ("ln(x), log(x), log(x, b), log2(x), exp(x)", "logarithms (log is base 10) and e^x"),
    ("sin, cos, tan, asin, acos, atan", "trigonometry in radians"),
    ("sind, cosd, tand, asind, acosd, atand", "trigonometry in degrees (exact at standard angles)"),
    ("gcd, lcm, comb(n,k), perm(n,k)", "whole-number functions"),
    ("isprime(n), factor(n)", "prime test and prime factorization"),
    ("mean(...), median(...), min, max, abs, round(x, d), floor, ceil", "lists and rounding (round half away from zero)"),
    ("pi, e, tau, phi", "constants"),
]


# ----------------------------------------------------------------------------- parsing
_WORDS = [
    (r"\bdivided by\b", "/"), (r"\bmultiplied by\b", "*"), (r"\btimes\b", "*"), (r"\bplus\b", "+"), (r"\bminus\b", "-"),
    (r"\bover\b", "/"), (r"\bmod(ulo)?\b", "%"), (r"\bto the power of\b", "^"), (r"\bsquared\b", "^2"), (r"\bcubed\b", "^3"),
    (r"\bsquare root of\b", "sqrt "), (r"\bcube root of\b", "cbrt "), (r"\bpercent of\b", "/100*"), (r"\bof\b", "*"),
]


def normalize_expression(text):
    """Turn everyday notation into the engine's syntax. Deterministic."""
    s = str(text or "").strip()
    s = re.sub(r"^\s*(what('?s| is)|calculate|compute|evaluate|how much is)\s+", "", s, flags=re.I)
    s = s.rstrip("?= ").strip()
    for a, b in [("×", "*"), ("·", "*"), ("÷", "/"), ("−", "-"), ("–", "-"), ("^", "**"), ("√", "sqrt"), ("²", "**2"), ("³", "**3"),
                 ("π", "pi"), ("，", ","), ("−", "-")]:
        s = s.replace(a, b)
    low = s.lower()
    for pat, rep in _WORDS:
        low = re.sub(pat, rep, low)
    s = low.replace("^", "**")
    s = re.sub(r"(\d+(\.\d+)?|\))\s*%(?!\s*[\d(a-z])", r"\1/100", s)     # 15% -> 15/100 (not modulo)
    s = re.sub(r"sqrt\s+(\d+(\.\d+)?)", r"sqrt(\1)", s)
    s = re.sub(r"cbrt\s+(\d+(\.\d+)?)", r"cbrt(\1)", s)
    # n!  ->  factorial(n)   (also (expr)!)
    for _ in range(5):
        s2 = re.sub(r"(\d+)\s*!", r"factorial(\1)", s)
        s2 = re.sub(r"(\([^()]*\))\s*!", r"factorial\1", s2)
        if s2 == s:
            break
        s = s2
    s = re.sub(r"(\d)\s*\(", r"\1*(", s)                      # 2(3+4) -> 2*(3+4)
    s = re.sub(r"\)\s*\(", ")*(", s)                          # (a)(b) -> (a)*(b)
    s = re.sub(r"(\d)\s*(pi|e|tau|phi)\b", r"\1*\2", s)        # 2pi -> 2*pi
    if re.fullmatch(r"[\d,.\s+\-*/()%]+", s):           # thousands separators: 1,000,000
        for _ in range(10):
            s2 = re.sub(r"(\d),(\d{3})(?!\d)", r"\1\2", s)
            if s2 == s:
                break
            s = s2
    return " ".join(s.split())


_BIN = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Div: "div", ast.Pow: "pow", ast.Mod: "mod", ast.FloorDiv: "floordiv"}


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float, Fraction)):
        raise CalcError("only numbers can be used here")
    return v


def _binop(op, a, b):
    a, b = _num(a), _num(b)
    exact = _exact(a) and _exact(b)
    if op == "add":
        return a + b if exact else _approx(_f(a) + _f(b))
    if op == "sub":
        return a - b if exact else _approx(_f(a) - _f(b))
    if op == "mul":
        r = a * b if exact else _approx(_f(a) * _f(b))
        if exact and _digits(r) > MAX_DIGITS:
            raise CalcError("result has more than %d digits" % MAX_DIGITS)
        return r
    if op in ("div", "floordiv", "mod"):
        if (b == 0) if exact else (_f(b) == 0):
            raise CalcError("division by zero is undefined")
        if op == "div":
            return Fraction(a) / Fraction(b) if exact else _approx(_f(a) / _f(b))
        if op == "floordiv":
            return Fraction(a) // Fraction(b) if exact else math.floor(_f(a) / _f(b))
        return Fraction(a) % Fraction(b) if exact else _approx(math.fmod(_f(a), _f(b)))
    if op == "pow":
        if exact and _to_frac(b).denominator == 1:
            k = int(b)
            if abs(k) > MAX_EXPONENT:
                raise CalcError("exponent too large (limit %d)" % MAX_EXPONENT)
            base = _to_frac(a)
            if base == 0 and k < 0:
                raise CalcError("0 to a negative power is undefined")
            est = abs(k) * max(1, math.log10(max(abs(base.numerator), abs(base.denominator), 1) + 1))
            if est > MAX_DIGITS + 5:
                raise CalcError("result has more than %d digits" % MAX_DIGITS)
            return base ** k
        if exact:
            fb = _to_frac(b)
            # exact rational powers like 8^(1/3) or 4^(3/2)
            r = _iroot_exact(_to_frac(a), fb.denominator) if fb.denominator <= 64 else None
            if r is not None:
                return r ** fb.numerator
        if _f(a) < 0 and not float(_f(b)).is_integer():
            raise CalcError("a negative number to a fractional power is not a real number")
        try:
            return _approx(_f(a) ** _f(b))
        except OverflowError:
            raise CalcError("result is too large")
    raise CalcError("unsupported operation")


def _digits(v):
    if isinstance(v, Fraction):
        return max(len(str(abs(v.numerator))), len(str(v.denominator)))
    if isinstance(v, int):
        return len(str(abs(v))) if abs(v) < 10 ** 6000 else 6001
    return 0


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalcError("only numbers can be used here")
        if isinstance(node.value, float):
            return Fraction(repr(node.value)) if "e" not in repr(node.value) or abs(node.value) < 1e300 else _approx(node.value)
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _num(_eval(node.operand))
        if isinstance(node.op, ast.UAdd):
            return v
        return -v if _exact(v) else _approx(-_f(v))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _binop(_BIN[type(node.op)], _eval(node.left), _eval(node.right))
    if isinstance(node, ast.Name):
        if _VARS.get() and node.id in _VARS.get():
            return _VARS.get()[node.id]
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        raise CalcError("unknown name '%s'" % node.id)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        fn = FUNCTIONS.get(node.func.id.lower())
        if fn is None:
            raise CalcError("unknown function '%s'" % node.func.id)
        args = [_eval(a) for a in node.args]
        try:
            return fn(*args)
        except TypeError:
            raise CalcError("wrong number of values for %s()" % node.func.id)
        except (ValueError, OverflowError) as e:
            raise CalcError(str(e))
    raise CalcError("this expression uses something the calculator does not allow")


import contextvars
_VARS = contextvars.ContextVar("qb_vars", default=None)


def evaluate_with(expr, values):
    """Evaluate an engine-syntax expression with named values (Fractions or floats)."""
    tok = _VARS.set({k: (Approx(v) if isinstance(v, float) else v) for k, v in values.items()})
    try:
        return _eval(ast.parse(expr, mode="eval"))
    finally:
        _VARS.reset(tok)


def evaluate(text):
    """Evaluate an expression. Returns a result dict; raises CalcError with a plain message."""
    expr = normalize_expression(text)
    if not expr:
        raise CalcError("type a calculation, for example 12 × 7 or sqrt(2)")
    if len(expr) > 2000:
        raise CalcError("expression too long")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        raise CalcError("could not read '%s' — check the brackets and operators" % text)
    v = _eval(tree)
    return describe(v, expr)


def describe(v, expr=""):
    if isinstance(v, str):
        return {"expression": expr, "exact": True, "display": v, "decimal": None, "fraction": None, "value": v}
    if isinstance(v, bool):
        raise CalcError("not a number")
    if _exact(v):
        fr = _to_frac(v)
        if fr.denominator == 1:
            n = fr.numerator
            disp = _group(n)
            return {"expression": expr, "exact": True, "display": disp, "decimal": disp, "fraction": None,
                    "value": str(n), "scientific": _sci(n) if abs(n) >= 10 ** 15 else None}
        dec = _decimal_string(fr)
        frac = "%d/%d" % (fr.numerator, fr.denominator)
        terminating = "(" not in dec and "…" not in dec
        small = len(str(abs(fr.numerator))) <= 12 and len(str(fr.denominator)) <= 12
        if terminating and len(dec) <= 40:
            disp = dec
        elif small:
            disp = frac
        else:
            disp = "≈ " + _fmt_float(float(fr))
            if len(frac) > 200:
                frac = "(exact fraction has %d digits)" % len(frac)
        return {"expression": expr, "exact": True, "display": disp,
                "decimal": dec if len(dec) <= 60 else _fmt_float(float(fr)), "fraction": frac, "value": "%d/%d" % (fr.numerator, fr.denominator)}
    x = float(v)
    return {"expression": expr, "exact": False, "display": "≈ " + _fmt_float(x), "decimal": _fmt_float(x), "fraction": None,
            "value": repr(x)}


def _group(n):
    s = str(abs(n))
    if len(s) <= 4:
        g = s
    else:
        g = ",".join([s[max(0, i - 3):i] for i in range(len(s), 0, -3)][::-1])
    return ("-" if n < 0 else "") + g


def _sci(n):
    s = str(abs(n))
    return ("-" if n < 0 else "") + s[0] + "." + s[1:7] + " × 10^" + str(len(s) - 1)


def _fmt_float(x):
    if x == 0:
        return "0"
    if abs(x) >= 1e15 or abs(x) < 1e-6:
        return "%.12g" % x
    return ("%.12f" % x).rstrip("0").rstrip(".")


def _decimal_string(fr, digits=30):
    """Exact decimal expansion; repeating part shown in brackets, e.g. 1/3 = 0.(3)."""
    sign = "-" if fr < 0 else ""
    fr = abs(fr)
    whole, rem = divmod(fr.numerator, fr.denominator)
    if rem == 0:
        return sign + str(whole)
    seen, out = {}, []
    while rem and rem not in seen and len(out) < digits:
        seen[rem] = len(out)
        rem *= 10
        out.append(str(rem // fr.denominator))
        rem %= fr.denominator
    if rem and rem in seen:
        i = seen[rem]
        return sign + str(whole) + "." + "".join(out[:i]) + "(" + "".join(out[i:]) + ")"
    return sign + str(whole) + "." + "".join(out) + ("…" if rem else "")


def same_value(a, b, tol=1e-9):
    """Compare two answer strings numerically (used to verify stored facts)."""
    def parse(s):
        s = str(s).replace(",", "").replace("≈", "").strip()
        try:
            return Fraction(s)
        except (ValueError, ZeroDivisionError):
            try:
                return float(s)
            except ValueError:
                return s
    x, y = parse(a), parse(b)
    if isinstance(x, str) or isinstance(y, str):
        return norm_text(x) == norm_text(y)
    if isinstance(x, Fraction) and isinstance(y, Fraction):
        return x == y
    return math.isclose(float(x), float(y), rel_tol=tol, abs_tol=tol)


def norm_text(s):
    return " ".join(str(s).lower().split())
