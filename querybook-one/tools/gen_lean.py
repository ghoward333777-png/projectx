#!/usr/bin/env python3
"""Generate the Lean 4 files that must mirror Python code exactly:

  lean/QueryBookOne/Formulas.lean   every solvable formula of apps/stem/science.py: one definition per solution and one
                                    theorem per solution saying that the solved value, put back into the defining
                                    equation, gives the original quantity back
  lean/QueryBookOne/UnitExamples.lean   unit conversions computed by apps/stem/units.py with exact fractions, checked in Lean

    python tools/gen_lean.py          write the files
    python tools/gen_lean.py --check  exit 1 if the committed files differ from what the Python code generates

tests/test_lean_sync.py runs --check, so a formula or unit changed in Python without the Lean proofs fails the build.
"""
from __future__ import annotations

import ast
import os
import sys
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEM = os.path.join(ROOT, "apps", "stem")
OUT = os.path.join(ROOT, "lean", "QueryBookOne")
sys.path.insert(0, STEM)

import science  # noqa: E402
import units  # noqa: E402

FUNCS = {"sqrt": "Real.sqrt", "ln": "Real.log", "sind": "sind", "asind": "asind"}
ANGLES = {"theta", "t1", "t2"}


def lit(fr: Fraction) -> str:
    fr = Fraction(fr)
    return "(%d : ℝ)" % fr.numerator if fr.denominator == 1 else "((%d : ℝ) / %d)" % (fr.numerator, fr.denominator)


def to_lean(expr: str, consts: dict[str, str], subst: dict[str, str] | None = None) -> str:
    """Python solution expression -> Lean term. Constants become exact fractions so positivity sees them."""
    subst = subst or {}

    def go(n: ast.AST, prec: int = 0) -> str:
        if isinstance(n, ast.Expression):
            return go(n.body)
        if isinstance(n, ast.Constant):
            return lit(Fraction(str(n.value)))
        if isinstance(n, ast.Name):
            if n.id in subst:
                return "(" + subst[n.id] + ")"
            if n.id == "pi":
                return "Real.pi"
            if n.id in consts:
                return lit(Fraction(consts[n.id]))
            return n.id
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return "(-" + go(n.operand, 9) + ")"
        if isinstance(n, ast.BinOp):
            ops = {ast.Add: ("+", 1), ast.Sub: ("-", 1), ast.Mult: ("*", 2), ast.Div: ("/", 2), ast.Pow: ("^", 3)}
            sym, p = ops[type(n.op)]
            left = go(n.left, p)
            right = go(n.right, p + (0 if sym == "^" else 1))
            if sym == "^" and isinstance(n.right, ast.Constant) and float(n.right.value).is_integer():
                right = str(int(n.right.value))               # natural-number power: x ^ 2
            s = "%s %s %s" % (left, sym, right)
            return "(" + s + ")" if p < prec or (sym == "^" and prec >= 3) else s
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS:
            return "%s (%s)" % (FUNCS[n.func.id], ", ".join(go(a) for a in n.args))
        raise ValueError("cannot translate %s" % ast.dump(n))

    return go(ast.parse(expr, mode="eval"))


# Formulas whose theorems need extra hypotheses or a hand-written proof (everything else: all quantities positive,
# then field_simp; ring). Each proof is checked by `lake build`.
EXTRA_HYPS = {
    ("parallel", "R1"): ["(h_lt : R < R2)"], ("parallel", "R2"): ["(h_lt : R < R1)"],
    ("suvat2", "u"): ["(h_le : 2 * a * s ≤ v ^ 2)"],
    ("pythagoras", "a"): ["(h_lt : b < c)"], ("pythagoras", "b"): ["(h_lt : a < c)"],
    ("projectile", "v"): ["(h_t1 : theta < 90)"], ("projectile", "g"): ["(h_t1 : theta < 90)"],
    ("projectile", "theta"): ["(h_le : Rg * g / v ^ 2 ≤ 1)"],
    ("snell", "t1"): ["(h_t2u : t2 < 90)", "(h_le : n2 * sind t2 / n1 ≤ 1)"],
    ("snell", "n2"): ["(h_t1u : t1 < 90)", "(h_t2u : t2 < 90)"],
    ("snell", "t2"): ["(h_t1u : t1 < 90)", "(h_le : n1 * sind t1 / n2 ≤ 1)"],
}
PROOFS = {
    ("parallel", "R1"): """
  simp only [parallel_R, parallel_R1]
  have hd : R2 - R ≠ 0 := (sub_pos.mpr h_lt).ne'
  have hs : 0 < R * R2 / (R2 - R) + R2 := add_pos (div_pos (mul_pos h_R h_R2) (sub_pos.mpr h_lt)) h_R2
  rw [div_eq_iff hs.ne']
  qb_field""",
    ("parallel", "R2"): """
  simp only [parallel_R, parallel_R2]
  have hd : R1 - R ≠ 0 := (sub_pos.mpr h_lt).ne'
  have hs : 0 < R1 + R * R1 / (R1 - R) := add_pos h_R1 (div_pos (mul_pos h_R h_R1) (sub_pos.mpr h_lt))
  rw [div_eq_iff hs.ne']
  qb_field""",
    ("suvat2", "u"): """
  simp only [suvat2_v, suvat2_u]
  rw [Real.sq_sqrt (by linarith), show v ^ 2 - 2 * a * s + 2 * a * s = v ^ 2 by ring]
  exact Real.sqrt_sq h_v.le""",
    ("suvat2", "a"): """
  simp only [suvat2_v, suvat2_a]
  have hs := h_s.ne'
  rw [show u ^ 2 + 2 * ((v ^ 2 - u ^ 2) / (2 * s)) * s = v ^ 2 by qb_field]
  exact Real.sqrt_sq h_v.le""",
    ("suvat2", "s"): """
  simp only [suvat2_v, suvat2_s]
  have ha := h_a.ne'
  rw [show u ^ 2 + 2 * a * ((v ^ 2 - u ^ 2) / (2 * a)) = v ^ 2 by qb_field]
  exact Real.sqrt_sq h_v.le""",
    ("pythagoras", "a"): """
  simp only [pythagoras_c, pythagoras_a]
  rw [Real.sq_sqrt (by nlinarith), show c ^ 2 - b ^ 2 + b ^ 2 = c ^ 2 by ring]
  exact Real.sqrt_sq h_c.le""",
    ("pythagoras", "b"): """
  simp only [pythagoras_c, pythagoras_b]
  rw [Real.sq_sqrt (by nlinarith), show a ^ 2 + (c ^ 2 - a ^ 2) = c ^ 2 by ring]
  exact Real.sqrt_sq h_c.le""",
    ("pendulum", "L"): """
  simp only [pendulum_T, pendulum_L]
  have hpi := Real.pi_pos
  rw [mul_div_cancel_left₀ _ h_g.ne', Real.sqrt_sq (by positivity)]
  qb_field""",
    ("pendulum", "g"): """
  simp only [pendulum_T, pendulum_g]
  have hpi := Real.pi_pos
  rw [show L / (L * (2 * Real.pi / T) ^ 2) = (T / (2 * Real.pi)) ^ 2 by qb_field, Real.sqrt_sq (by positivity)]
  qb_field""",
    ("projectile", "v"): """
  simp only [projectile_Rg, projectile_v]
  have hs := sind_pos (2 * theta) (by linarith) (by linarith)
  rw [Real.sq_sqrt (by positivity)]
  qb_field""",
    ("projectile", "g"): """
  simp only [projectile_Rg, projectile_g]
  have hs := sind_pos (2 * theta) (by linarith) (by linarith)
  qb_field""",
    ("projectile", "theta"): """
  simp only [projectile_Rg, projectile_theta]
  rw [show 2 * (asind (Rg * g / v ^ 2) / 2) = asind (Rg * g / v ^ 2) by ring,
      sind_asind _ (by linarith [show (0 : ℝ) ≤ Rg * g / v ^ 2 by positivity]) h_le]
  qb_field""",
    ("snell", "t1"): """
  simp only [snell_n1, snell_t1]
  have h2 := sind_pos t2 h_t2 (by linarith)
  rw [sind_asind _ (by linarith [show (0 : ℝ) ≤ n2 * sind t2 / n1 by positivity]) h_le]
  qb_field""",
    ("snell", "n2"): """
  simp only [snell_n1, snell_n2]
  have h1 := sind_pos t1 h_t1 (by linarith)
  have h2 := sind_pos t2 h_t2 (by linarith)
  qb_field""",
    ("snell", "t2"): """
  simp only [snell_n1, snell_t2]
  have h1 := sind_pos t1 h_t1 (by linarith)
  rw [sind_asind _ (by linarith [show (0 : ℝ) ≤ n1 * sind t1 / n2 by positivity]) h_le]
  qb_field""",
    ("interest", "P"): """
  simp only [interest_Amt, interest_P]
  have hb : 0 < (1 : ℝ) + rate / n := by positivity
  have hp := (Real.rpow_pos_of_pos hb (n * t)).ne'
  qb_field""",
    ("interest", "t"): """
  simp only [interest_Amt, interest_t]
  have hb : 1 < (1 : ℝ) + rate / n := by linarith [show (0 : ℝ) < rate / n by positivity]
  have hl := (Real.log_pos hb).ne'
  have hn := h_n.ne'
  rw [Real.rpow_def_of_pos (by linarith),
      show Real.log (1 + rate / n) * (n * (Real.log (Amt / P) / (n * Real.log (1 + rate / n)))) = Real.log (Amt / P) by
        qb_field,
      Real.exp_log (by positivity)]
  qb_field""",
}
DEFAULT_PROOF = """
  simp only [{defs}]
{haves}  qb_field"""
SQRT_PROOF = """
  simp only [{defs}]
{haves}  rw [Real.sq_sqrt (by positivity)]
  qb_field"""


def ident(fid: str, var: str) -> str:
    return "%s_%s" % (fid, var)


def formulas_lean() -> str:
    out = ["-- GENERATED by tools/gen_lean.py from apps/stem/science.py — do not edit by hand.",
           "-- Every solvable formula of the STEM application: a definition per solution and a theorem per solution saying",
           "-- that the solved value, put back into the formula, gives the original quantity back.",
           "import Mathlib",
           "import QueryBookOne.Degrees",
           "",
           "namespace QueryBookOne.Formulas",
           "",
           "open QueryBookOne.Degrees",
           ""]
    count = 0
    for fid, name, field, disp, vars_, sol, consts in science.FORMULAS:
        names = [v for v, _, _, _ in vars_]
        out.append("/-! ### %s (%s): %s -/" % (name, field, disp))
        for x in names:
            if x not in sol:
                continue
            args = [v for v in names if v != x]
            out.append("noncomputable def %s (%s : ℝ) : ℝ := %s" % (ident(fid, x), " ".join(args), to_lean(sol[x], consts)))
        v0 = names[0]
        for x in names:
            if x == v0 or x not in sol:
                continue
            args = [v for v in names if v != x]
            call_x = "%s %s" % (ident(fid, x), " ".join(args))
            call_v0 = "%s %s" % (ident(fid, v0), " ".join("(%s)" % call_x if v == x else v for v in names if v != v0))
            hyps = ["(h_%s : 0 < %s)" % (v, v) for v in args] + EXTRA_HYPS.get((fid, x), [])
            proof = PROOFS.get((fid, x))
            if proof is None:
                haves = "".join("  have h%s := h_%s.ne'\n" % (v, v) for v in args) + "  have hpi := Real.pi_pos.ne'\n"
                tmpl = SQRT_PROOF if sol[x].startswith("sqrt(") else DEFAULT_PROOF
                proof = tmpl.format(defs="%s, %s" % (ident(fid, v0), ident(fid, x)), haves=haves)
            out.append("theorem %s_recomputes_%s (%s : ℝ)\n    %s :\n    %s = %s := by%s"
                       % (ident(fid, x), v0, " ".join(args), " ".join(hyps), call_v0, v0, proof))
            count += 1
        out.append("")
    out.append("-- %d theorems for %d formulas." % (count, len(science.FORMULAS)))
    out.append("end QueryBookOne.Formulas")
    return "\n".join(out) + "\n"


UNIT_CASES = [("60", "mph", "km/h"), ("1", "mi", "km"), ("1", "ft", "m"), ("1", "lb", "kg"), ("1", "gal", "L"), ("1", "atm", "psi"),
              ("1", "kWh", "MJ"), ("1", "hp", "W"), ("100", "km/h", "m/s"), ("1", "acre", "ha"), ("1", "BTU", "kJ"), ("1", "knot", "km/h")]
TEMP_CASES = [("100", "°C", "°F"), ("32", "°F", "°C"), ("0", "°C", "K"), ("300", "K", "°C")]


def units_lean() -> str:
    out = ["-- GENERATED by tools/gen_lean.py from apps/stem/units.py — do not edit by hand.",
           "-- Each line is a conversion the STEM application performs with exact fractions; Lean checks the same arithmetic.",
           "import Mathlib",
           "import QueryBookOne.Units",
           "",
           "namespace QueryBookOne.UnitExamples",
           "",
           "open QueryBookOne.Units",
           ""]
    for v, src, dst in UNIT_CASES:
        fs, _ = units.parse_unit(src)
        fd, _ = units.parse_unit(dst)
        res = units.convert_value(Fraction(v), src, dst)
        exact = Fraction(Fraction(v) * fs / fd)
        if res["exact"]:                                  # the application's own answer must equal the proved value
            assert Fraction(res["result"].replace(",", "").replace(" ", "")) == exact, (v, src, dst, res)
        out.append("-- STEM: %s" % res["display"])
        out.append("example : convert %s %s %s = %s := by norm_num [convert]" % (qlit(Fraction(v)), qlit(fs), qlit(fd), qlit(exact)))
    for v, src, dst in TEMP_CASES:
        ts, td = units.TEMPS[src], units.TEMPS[dst]
        exact = (Fraction(v) * ts[1] + ts[2] - td[2]) / td[1]
        out.append("-- STEM: %s" % units.convert_value(Fraction(v), src, dst)["display"])
        out.append("example : temperature %s %s %s %s %s = %s := by norm_num [temperature]"
                   % (qlit(Fraction(v)), qlit(ts[1]), qlit(ts[2]), qlit(td[1]), qlit(td[2]), qlit(exact)))
    out += ["", "end QueryBookOne.UnitExamples"]
    return "\n".join(out) + "\n"


def qlit(fr: Fraction) -> str:
    fr = Fraction(fr)
    return "(%d : ℚ)" % fr.numerator if fr.denominator == 1 else "((%d : ℚ) / %d)" % (fr.numerator, fr.denominator)


FILES = {"Formulas.lean": formulas_lean, "UnitExamples.lean": units_lean}

if __name__ == "__main__":
    check = "--check" in sys.argv
    bad = []
    for name, fn in FILES.items():
        text = fn()
        path = os.path.join(OUT, name)
        if check:
            try:
                with open(path, encoding="utf-8") as f:
                    if f.read() != text:
                        bad.append(name)
            except OSError:
                bad.append(name)
        else:
            os.makedirs(OUT, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print("wrote", os.path.relpath(path, ROOT))
    if bad:
        print("Out of date (run tools/gen_lean.py):", ", ".join(bad))
        sys.exit(1)
