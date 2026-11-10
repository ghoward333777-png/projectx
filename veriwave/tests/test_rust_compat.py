"""VeriWave's engine stays directly translatable to Rust (the rule QueryBook Next and QueryBook one already enforce):
no reflection or code generation, no *args/**kwargs, every function fully annotated, standard library only."""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANNED = {"eval", "exec", "compile", "getattr", "setattr", "delattr", "hasattr", "globals", "locals", "vars", "__import__", "type"}
ALLOWED = {"__future__", "json", "math", "typing", "dataclasses", "hashlib", "html", "io", "os", "struct", "threading",
           "time", "urllib", "wave", "zipfile", "base64", "shutil", "socket", "subprocess", "sys", "http",
           "tempfile", "webbrowser", "sqlite3", "gzip"}
# vw: VeriWave itself; shell/ask: QueryBook one's own modules (ask.py is already on QueryBook's Rust-ported list)
LOCAL = {"vw", "shell", "ask"}
# standard-library methods whose signature VeriWave must match when it overrides them
STDLIB_OVERRIDES = {"log_message"}


class RustCompatTest(unittest.TestCase):
    def test_engine_modules(self):
        bad = []
        files = [os.path.join("vw", f) for f in sorted(os.listdir(os.path.join(ROOT, "vw"))) if f.endswith(".py")] + ["veriwave.py"]
        for rel in files:
            tree = ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read())
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in BANNED:
                    bad.append("%s:%d %s()" % (rel, n.lineno, n.func.id))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if (n.args.kwarg or n.args.vararg) and n.name not in STDLIB_OVERRIDES:
                        bad.append("%s:%d *args/**kwargs in %s" % (rel, n.lineno, n.name))
                    missing = [a.arg for a in n.args.args + n.args.kwonlyargs if a.annotation is None and a.arg != "self"]
                    if missing or n.returns is None:
                        bad.append("%s:%d %s not fully annotated %s" % (rel, n.lineno, n.name, missing))
                if isinstance(n, ast.Lambda):
                    pass                                         # closures port to Rust closures
                if isinstance(n, ast.Import):
                    for a in n.names:
                        if a.name.split(".")[0] not in ALLOWED | LOCAL:
                            bad.append("%s:%d imports %s" % (rel, n.lineno, a.name))
                if isinstance(n, ast.ImportFrom) and n.level == 0:
                    if (n.module or "").split(".")[0] not in ALLOWED | LOCAL:
                        bad.append("%s:%d imports %s" % (rel, n.lineno, n.module))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
