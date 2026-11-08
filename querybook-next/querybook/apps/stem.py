"""STEM app — answers come back as a worked solution: the evaluated result with
every intermediate step, plus matching formulas and quantities from the corpus."""

from __future__ import annotations

import ast
import math
import re
from typing import Any

from querybook.apps.base import DomainApp, QueryContext, fql_str, source_ref
from querybook.core.model import DOMAIN_COLLECTIONS
from querybook.core.text import STOPWORDS, tokenize

UNITS = ("km", "m", "cm", "mm", "nm", "kg", "g", "mg", "s", "ms", "min", "h", "N", "J", "kJ", "W", "kW", "Pa", "kPa",
         "mol", "K", "°C", "Hz", "kHz", "MHz", "GHz", "V", "A", "Ω", "C", "eV", "m/s", "m/s²", "m/s^2", "L", "mL")
QUANTITY = re.compile(r"(?<![\w.])(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s?(" +
                      "|".join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True)) + r")(?![\w/])")
FORMULA = re.compile(r"(?<![\w=<>!])([A-Za-z][A-Za-z0-9_]{0,15})\s*=\s*([A-Za-z0-9_.\s+\-*/^()²³√]{1,80}?)"
                     r"(?=$|[,;:]|\.\s|\.$|\s(?:where|with|and|which|for)\b)", re.M)
SUBJECTS = {
    "physics": {"force", "energy", "mass", "velocity", "acceleration", "gravity", "momentum", "wave", "photon", "newton"},
    "chemistry": {"atom", "molecule", "reaction", "compound", "element", "bond", "acid", "mole", "electron"},
    "biology": {"cell", "gene", "protein", "organism", "species", "evolution", "enzyme", "dna"},
    "mathematics": {"theorem", "proof", "integral", "derivative", "matrix", "vector", "equation", "function", "prime"},
    "computing": {"algorithm", "data", "complexity", "program", "binary", "memory"},
    "engineering": {"circuit", "voltage", "current", "resistance", "load", "power"},
}
FUNCS = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos,
         "atan": math.atan, "log": math.log, "ln": math.log, "log10": math.log10, "log2": math.log2, "exp": math.exp,
         "abs": abs, "floor": math.floor, "ceil": math.ceil, "round": round, "factorial": math.factorial}
CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "g": 9.80665, "c": 299_792_458}
OPS = {ast.Add: "+", ast.Sub: "−", ast.Mult: "×", ast.Div: "÷", ast.Pow: "^", ast.Mod: "mod", ast.FloorDiv: "div"}
LEAD = re.compile(r"^(?:please\s+)?(?:calculate|compute|evaluate|solve|simplify|what is|what's|find)\s+", re.I)


class MathError(ValueError):
    pass


def fmt(v: float | int) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int) or (isinstance(v, float) and v.is_integer() and abs(v) < 1e15):
        return f"{int(v):,}".replace(",", " ") if abs(v) >= 10000 else str(int(v))
    return f"{v:.10g}"


def prepare(expr: str) -> str:
    expr = expr.replace("^", "**").replace("×", "*").replace("·", "*").replace("÷", "/").replace("−", "-")
    expr = expr.replace("²", "**2").replace("³", "**3")
    expr = re.sub(r"√\s*\(", "sqrt(", expr)
    expr = re.sub(r"√\s*([0-9.]+|[A-Za-z_]\w*)", r"sqrt(\1)", expr)
    expr = re.sub(r"(\d)\s*([A-Za-z(])", r"\1*\2", expr)  # 2x -> 2*x, 3(4) -> 3*(4)
    expr = re.sub(r"\b(sqrt|sin|cos|tan|asin|acos|atan|log|ln|log10|log2|exp|abs|floor|ceil|round|factorial)\*\(", r"\1(", expr)
    return expr.strip()


def evaluate(expr: str, variables: dict[str, float] | None = None) -> tuple[float, list[str]]:
    """Safely evaluate arithmetic; returns (value, human-readable steps)."""
    names = {**CONSTANTS, **(variables or {})}
    steps: list[str] = []
    try:
        tree = ast.parse(prepare(expr), mode="eval")
    except SyntaxError:
        raise MathError("That is not an expression I can evaluate.") from None

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise MathError(f"Unknown variable '{node.id}'")
            if node.id in (variables or {}):
                steps.append(f"{node.id} = {fmt(names[node.id])}")
            return names[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = walk(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            a, b = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and (abs(b) > 1000 or abs(a) > 1e100):
                raise MathError("That power is too large to evaluate.")
            try:
                v = {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b, ast.Div: lambda: a / b,
                     ast.Pow: lambda: a ** b, ast.Mod: lambda: a % b, ast.FloorDiv: lambda: a // b}[type(node.op)]()
            except ZeroDivisionError:
                raise MathError("Division by zero.") from None
            if isinstance(v, complex):
                raise MathError("The result is not a real number.")
            steps.append(f"{fmt(a)} {OPS[type(node.op)]} {fmt(b)} = {fmt(v)}")
            return v
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS and not node.keywords:
            args = [walk(a) for a in node.args]
            if not 1 <= len(args) <= 2:
                raise MathError(f"{node.func.id}() takes one argument")
            if node.func.id == "factorial" and (args[0] > 500 or args[0] != int(args[0])):
                raise MathError("factorial() takes a whole number up to 500")
            try:
                v = FUNCS[node.func.id](*([int(args[0])] if node.func.id == "factorial" else args))
            except (ValueError, OverflowError) as exc:
                raise MathError(f"{node.func.id}() is undefined there ({exc})") from None
            steps.append(f"{node.func.id}({', '.join(fmt(a) for a in args)}) = {fmt(v)}")
            return v
        raise MathError("Only numbers, + − × ÷ ^, parentheses and standard functions are allowed.")

    value = walk(tree)
    return value, steps


def extract_formulas(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in FORMULA.finditer(text):
        lhs, rhs = m.group(1), m.group(2).strip().rstrip(".")
        if not re.search(r"[A-Za-z]", rhs) and not re.search(r"[+\-*/^]", rhs):
            continue
        if not re.search(r"[+\-*/^²³√()]|[A-Za-z]\s*[A-Za-z]", rhs) and len(rhs.split()) > 1:
            continue
        variables = sorted({v for v in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", rhs) if v not in FUNCS})
        expr = f"{lhs} = {rhs}"
        if all(f["expr"] != expr for f in out):
            out.append({"expr": expr, "lhs": lhs, "rhs": rhs, "vars": variables})
    return out[:20]


class StemApp(DomainApp):
    key = "stem"
    title = "STEM"
    collection = DOMAIN_COLLECTIONS["stem"]
    tagline = "Worked solutions, formulas and quantities"
    placeholder = "Expression or formula — e.g. F = m * a where m = 2, a = 9.8"
    examples = ("(3 + 4) * 2^3", "F = m * a where m = 70, a = 9.81", "kinetic energy", "sqrt(2) * pi")

    def enrich(self, title: str, body: str) -> dict[str, Any]:
        text = f"{title}\n{body}"
        toks = set(tokenize(text))
        scores = {s: len(toks & words) for s, words in SUBJECTS.items()}
        subject = max(scores, key=lambda s: (scores[s], s)) if any(scores.values()) else "general"
        quantities = [{"value": float(v), "unit": u} for v, u in QUANTITY.findall(text)][:20]
        return {"subject": subject, "formulas": extract_formulas(text), "quantities": quantities}

    def respond(self, ctx: QueryContext, query: str) -> dict[str, Any]:
        q = LEAD.sub("", query.strip()).rstrip("?").strip()
        expr, target, variables = q, None, {}
        m = re.match(r"^(.*?)\s*(?:,\s*)?\b(?:where|with|given|for)\b\s+(.+)$", q, re.I)
        if m:
            expr = m.group(1)
            for name, val in re.findall(r"([A-Za-z_]\w*)\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", m.group(2)):
                variables[name] = float(val) if any(c in val for c in ".eE") else int(val)
        fm = re.match(r"^\s*([A-Za-z_]\w*)\s*=\s*(.+)$", expr)
        if fm:
            target, expr = fm.group(1), fm.group(2)
        solution, error = None, None
        if re.search(r"[\d)]", expr) or variables or re.search(r"[+\-*/^×÷√]", expr):
            try:
                value, steps = evaluate(expr, variables)
                solution = {"target": target, "expression": expr.strip(), "value": value, "display": fmt(value),
                            "steps": steps, "variables": {k: fmt(v) for k, v in variables.items()}}
            except MathError as exc:
                error = str(exc)
        terms = " ".join(t for t in tokenize(q) if not t.isdigit() and t not in STOPWORDS and len(t) > 1)
        docs = ctx.docs(f"Stem.search({fql_str(terms or q)}).take(12)") if (terms or not solution) else []
        formulas, quantities, subjects = [], [], {}
        qtoks = set(tokenize(q))
        for doc in docs:
            subjects[doc.get("subject", "general")] = subjects.get(doc.get("subject", "general"), 0) + 1
            for f in doc.get("formulas") or []:
                score = len(qtoks & set(tokenize(f["expr"])))
                formulas.append({**f, "source": doc.get("title", ""), "id": doc.get("id"), "score": score})
            for qty in (doc.get("quantities") or [])[:4]:
                quantities.append({**qty, "source": doc.get("title", "")})
        formulas.sort(key=lambda f: -f["score"])
        if solution:
            summary = f"{(solution['target'] + ' = ') if solution['target'] else ''}{solution['display']}"
        elif error and not formulas:
            summary = error
        elif formulas:
            summary = f"{len(formulas)} formula{'s' if len(formulas) != 1 else ''} found. Add values with “where x = …” to evaluate."
        else:
            summary = "Nothing in the STEM collection matches yet."
        return {"kind": "solution", "summary": summary, "subject": terms or q, "solution": solution, "error": error,
                "formulas": formulas[:12], "quantities": quantities[:12],
                "subjects": sorted(subjects, key=lambda s: -subjects[s]), "sources": [source_ref(d) for d in docs]}
