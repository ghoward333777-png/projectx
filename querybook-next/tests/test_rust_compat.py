"""Rules that keep the Python a direct translation target for Rust (see docs/DESIGN.md, "Rust compatibility").

* No runtime reflection or code generation: eval, exec, compile, getattr/setattr/delattr/hasattr,
  globals(), locals(), vars(), __dict__, __getattr__, metaclasses. (Rust has none of these.)
* No **kwargs anywhere and no *args except where documented (closures called with a fixed arity).
* Every function in querybook/core and querybook/ingest is fully annotated (parameters and return),
  so each signature maps to one Rust fn signature.
* Only the standard library is imported, and only modules on the allowlist (each has a named Rust
  counterpart in the design doc).
* Records crossing module boundaries are frozen dataclasses (=> Rust structs).
"""

import ast
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "querybook"
BANNED_CALLS = {"eval", "exec", "compile", "getattr", "setattr", "delattr", "hasattr", "globals", "locals", "vars", "__import__"}
BANNED_ATTRS = {"__dict__", "__getattr__", "__setattr__", "__class__", "__subclasses__"}
STRICT = ("core", "ingest")
ALLOWED_IMPORTS = {
    "__future__", "ast", "contextlib", "csv", "dataclasses", "hashlib", "html", "http", "io", "itertools", "json", "math", "mimetypes",
    "os", "pathlib", "re", "shutil", "sqlite3", "subprocess", "sys", "textwrap", "threading", "time", "typing",
    "unicodedata", "urllib", "webbrowser", "xml", "argparse", "querybook",
}
STAR_ARGS_ALLOWED = {("core/fql/evaluator.py", "__call__"),     # FQL lambdas: arity checked at call time
                     ("server/http.py", "log_message")}         # stdlib override; the server is not ported (axum)


def modules():
    return sorted(p for p in PKG.rglob("*.py"))


class RustCompatTest(unittest.TestCase):
    def test_no_reflection_or_codegen(self):
        bad = []
        for path in modules():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS:
                    bad.append(f"{path.relative_to(PKG)}:{node.lineno} {node.func.id}()")
                if isinstance(node, ast.Attribute) and node.attr in BANNED_ATTRS:
                    bad.append(f"{path.relative_to(PKG)}:{node.lineno} .{node.attr}")
                if isinstance(node, ast.ClassDef) and any(k.arg == "metaclass" for k in node.keywords):
                    bad.append(f"{path.relative_to(PKG)}:{node.lineno} metaclass")
        self.assertEqual(bad, [])

    def test_no_kwargs_and_fixed_arity(self):
        bad = []
        for path in modules():
            rel = path.relative_to(PKG).as_posix()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.args.kwarg:
                        bad.append(f"{rel}:{node.lineno} **{node.args.kwarg.arg}")
                    if node.args.vararg and (rel, node.name) not in STAR_ARGS_ALLOWED:
                        bad.append(f"{rel}:{node.lineno} *{node.args.vararg.arg} in {node.name}")
        self.assertEqual(bad, [])

    def test_core_and_ingest_are_fully_annotated(self):
        bad = []
        for path in modules():
            rel = path.relative_to(PKG).as_posix()
            if not rel.startswith(STRICT):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
                    missing = [a.arg for a in args if a.annotation is None and a.arg not in ("self", "cls")]
                    if missing or node.returns is None:
                        bad.append(f"{rel}:{node.lineno} {node.name} {missing or ''}{'' if node.returns else ' -> ?'}")
        self.assertEqual(bad, [])

    def test_standard_library_only(self):
        bad = []
        for path in modules():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                for n in names:
                    if n.split(".")[0] not in ALLOWED_IMPORTS:
                        bad.append(f"{path.relative_to(PKG)}:{node.lineno} import {n}")
        self.assertEqual(bad, [])

    def test_boundary_records_are_frozen_dataclasses(self):
        src = ast.parse((PKG / "core" / "model.py").read_text(encoding="utf-8"))
        classes = [n for n in src.body if isinstance(n, ast.ClassDef)]
        self.assertTrue(classes)
        for c in classes:
            deco = [ast.unparse(d) for d in c.decorator_list]
            self.assertIn("dataclass(frozen=True)", deco, c.name)


if __name__ == "__main__":
    unittest.main()
