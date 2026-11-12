"""The modules that are ported to Rust must stay directly translatable: no reflection or code generation, no **kwargs,
every function fully annotated, standard library only."""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORTED = [os.path.join("apps", "_core", "qbmath.py"), os.path.join("apps", "shell", "ask.py"), os.path.join("apps", "shell", "modes.py"),
          os.path.join("apps", "shell", "bookq.py"), os.path.join("apps", "shell", "caps.py"), os.path.join("apps", "shell", "sense.py")]
BANNED = {"eval", "exec", "compile", "getattr", "setattr", "delattr", "hasattr", "globals", "locals", "vars", "__import__"}
ALLOWED = {"__future__", "json", "re", "threading", "urllib", "math", "typing", "dataclasses", "sense"}


class RustCompatTest(unittest.TestCase):
    def test_ported_modules(self):
        bad = []
        for rel in PORTED:
            tree = ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read())
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in BANNED:
                    bad.append("%s:%d %s()" % (rel, n.lineno, n.func.id))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if n.args.kwarg or n.args.vararg:
                        bad.append("%s:%d *args/**kwargs in %s" % (rel, n.lineno, n.name))
                    missing = [a.arg for a in n.args.args + n.args.kwonlyargs if a.annotation is None and a.arg != "self"]
                    if missing or n.returns is None:
                        bad.append("%s:%d %s not fully annotated %s" % (rel, n.lineno, n.name, missing))
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    for name in ([a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]):
                        if name.split(".")[0] not in ALLOWED:
                            bad.append("%s:%d imports %s" % (rel, n.lineno, name))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
