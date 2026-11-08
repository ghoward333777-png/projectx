"""Tree-walking FQL evaluator over an FQLStore.

Sets are lazy (take/first stop scanning early); arrays are plain lists. Field
access on a missing field yields null, and comparisons against null are false,
so ad-hoc queries over schemaless harvested documents never crash on gaps.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from querybook.core.fql import ast as A
from querybook.core.fql.errors import FQLError
from querybook.core.fql.parser import parse
from querybook.core.model import Document
from querybook.core.store import COLLECTION_NAME, StoreError

THIS = "__this__"
FUNC_ARG_METHODS = frozenset({"where", "map", "flatMap", "firstWhere", "any", "every"})
MUTATIONS = frozenset({"create", "update", "replace", "delete"})


@dataclass(frozen=True)
class DocRef:
    doc: Document


@dataclass(frozen=True)
class CollRef:
    name: str


@dataclass(frozen=True)
class CollectionNamespace:
    pass


@dataclass(frozen=True)
class Ordering:
    key: Callable[[Any], Any]
    reverse: bool


class FSet:
    """A lazy, re-iterable set of values (Fauna's Set)."""

    def __init__(self, factory: Callable[[], Iterator[Any]]):
        self.factory = factory

    def __iter__(self) -> Iterator[Any]:
        return self.factory()


class Fn:
    def __init__(self, params: tuple[str, ...], body: A.Node, env: dict[str, Any], ev: "Evaluator"):
        self.params, self.body, self.env, self.ev = params, body, env, ev

    def __call__(self, *args: Any) -> Any:
        env = dict(self.env)
        for i, p in enumerate(self.params):
            env[p] = args[i] if i < len(args) else None
        return self.ev.eval(self.body, env)


def truthy(v: Any) -> bool:
    return v is not None and v is not False


def sort_key(v: Any) -> tuple:
    if v is None:
        return (0, 0)
    if isinstance(v, bool):
        return (1, v)
    if isinstance(v, (int, float)):
        return (2, v)
    if isinstance(v, str):
        return (3, v.lower(), v)
    if isinstance(v, DocRef):
        return (4, v.doc.coll, v.doc.id)
    return (5, str(v))


def type_name(v: Any) -> str:
    if v is None:
        return "Null"
    if isinstance(v, bool):
        return "Boolean"
    if isinstance(v, int):
        return "Int"
    if isinstance(v, float):
        return "Double"
    if isinstance(v, str):
        return "String"
    if isinstance(v, list):
        return "Array"
    if isinstance(v, dict):
        return "Object"
    if isinstance(v, DocRef):
        return "Document"
    if isinstance(v, FSet):
        return "Set"
    if isinstance(v, CollRef):
        return "Collection"
    if isinstance(v, (Fn, Ordering)) or callable(v):
        return "Function"
    return type(v).__name__


def to_json(v: Any, limit: int = 1000) -> Any:
    if isinstance(v, DocRef):
        return v.doc.to_json()
    if isinstance(v, FSet):
        items = list(itertools.islice(iter(v), limit + 1))
        out: dict[str, Any] = {"data": [to_json(x, limit) for x in items[:limit]]}
        if len(items) > limit:
            out["truncated"] = True
        return out
    if isinstance(v, list):
        return [to_json(x, limit) for x in v[:limit]]
    if isinstance(v, dict):
        return {k: to_json(x, limit) for k, x in v.items()}
    if isinstance(v, CollRef):
        return {"collection": v.name}
    if isinstance(v, (Fn, Ordering, CollectionNamespace)):
        return f"<{type_name(v)}>"
    return v


class Evaluator:
    def __init__(self, store: Any, *, readonly: bool = False, limit: int = 1000):
        self.store = store
        self.readonly = readonly
        self.limit = limit

    # -- entry points ---------------------------------------------------
    def evaluate(self, src: str) -> Any:
        return self.eval(parse(src), {})

    def run(self, src: str) -> Any:
        return to_json(self.evaluate(src), self.limit)

    # -- core -----------------------------------------------------------
    def eval(self, node: A.Node, env: dict[str, Any]) -> Any:
        method = getattr(self, "_eval_" + type(node).__name__)
        try:
            return method(node, env)
        except StoreError as exc:
            raise FQLError(exc.code, str(exc), node.pos) from None

    def _eval_Literal(self, node: A.Literal, env):
        return node.value

    def _eval_Ident(self, node: A.Ident, env):
        if node.name in env:
            return env[node.name]
        if node.name == "Collection":
            return CollectionNamespace()
        if COLLECTION_NAME.match(node.name):
            return CollRef(node.name)
        raise FQLError("unbound_variable", f"Unknown name '{node.name}'", node.pos)

    def _eval_FieldPath(self, node: A.FieldPath, env):
        if THIS not in env:
            raise FQLError("invalid_field_access",
                           "A '.field' shorthand only works inside where(), map(), order() and similar", node.pos)
        value = env[THIS]
        for name in node.path:
            value = self.member(value, name, node.pos)
        return value

    def _eval_Member(self, node: A.Member, env):
        return self.member(self.eval(node.obj, env), node.name, node.pos)

    def _eval_Index(self, node: A.Index, env):
        obj, idx = self.eval(node.obj, env), self.eval(node.index, env)
        if isinstance(obj, (list, str)) and isinstance(idx, int) and not isinstance(idx, bool):
            return obj[idx] if -len(obj) <= idx < len(obj) else None
        if isinstance(idx, str):
            return self.member(obj, idx, node.pos)
        raise FQLError("type_error", f"Cannot index {type_name(obj)} with {type_name(idx)}", node.pos)

    def _eval_Unary(self, node: A.Unary, env):
        v = self.eval(node.operand, env)
        if node.op == "!":
            return not truthy(v)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return -v
        raise FQLError("type_error", f"Cannot negate {type_name(v)}", node.pos)

    def _eval_Binary(self, node: A.Binary, env):
        op = node.op
        if op == "&&":
            return truthy(self.eval(node.left, env)) and truthy(self.eval(node.right, env))
        if op == "||":
            return truthy(self.eval(node.left, env)) or truthy(self.eval(node.right, env))
        a, b = self.eval(node.left, env), self.eval(node.right, env)
        if op == "==":
            return self.equal(a, b)
        if op == "!=":
            return not self.equal(a, b)
        num = (int, float)
        both_num = isinstance(a, num) and isinstance(b, num) and not isinstance(a, bool) and not isinstance(b, bool)
        if op in ("<", "<=", ">", ">="):
            if a is None or b is None:
                return False
            if not (both_num or (isinstance(a, str) and isinstance(b, str))):
                raise FQLError("type_error", f"Cannot compare {type_name(a)} with {type_name(b)}", node.pos)
            return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
        if op == "+":
            if both_num:
                return a + b
            if isinstance(a, str) or isinstance(b, str):
                return f"{'' if a is None else a}{'' if b is None else b}"
            if isinstance(a, list) and isinstance(b, list):
                return a + b
        if both_num:
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if op in ("/", "%"):
                if b == 0:
                    raise FQLError("divide_by_zero", "Division by zero", node.pos)
                if op == "%":
                    return a % b
                if isinstance(a, int) and isinstance(b, int) and a % b == 0:
                    return a // b
                return a / b
        raise FQLError("type_error", f"Operator '{op}' does not apply to {type_name(a)} and {type_name(b)}", node.pos)

    def _eval_Lambda(self, node: A.Lambda, env):
        return Fn(node.params, node.body, env, self)

    def _eval_ArrayLit(self, node: A.ArrayLit, env):
        return [self.eval(x, env) for x in node.items]

    def _eval_ObjectLit(self, node: A.ObjectLit, env):
        return {k: self.eval(v, env) for k, v in node.pairs}

    def _eval_Let(self, node: A.Let, env):
        inner = dict(env)
        inner[node.name] = self.eval(node.value, env)
        return self.eval(node.body, inner)

    def _eval_Projection(self, node: A.Projection, env):
        target = self.eval(node.obj, env)

        def project(el: Any) -> Any:
            if el is None:
                return None
            out: dict[str, Any] = {}
            for name, expr in node.fields:
                out[name] = self.member(el, name, node.pos) if expr is None else self.eval(expr, {**env, THIS: el})
            return out

        if isinstance(target, FSet):
            return FSet(lambda: (project(x) for x in target))
        if isinstance(target, list):
            return [project(x) for x in target]
        return project(target)

    def _eval_FuncCall(self, node: A.FuncCall, env):
        if node.name in ("asc", "desc"):
            if len(node.args) != 1:
                raise FQLError("invalid_argument", f"{node.name}() takes one field accessor", node.pos)
            return Ordering(self.fn_arg(node.args[0], env), node.name == "desc")
        fn = env.get(node.name)
        if isinstance(fn, Fn):
            return fn(*[self.eval(a, env) for a in node.args])
        raise FQLError("unbound_variable", f"Unknown function '{node.name}'", node.pos)

    def _eval_MethodCall(self, node: A.MethodCall, env):
        obj = self.eval(node.obj, env)
        if self.readonly and node.name in MUTATIONS and isinstance(obj, (CollRef, DocRef)):
            raise FQLError("readonly", f"{node.name}() is not allowed in a read-only query", node.pos)
        if node.name in FUNC_ARG_METHODS:
            args = [self.fn_arg(a, env) for a in node.args]
        elif node.name == "order":
            args = [self.eval(a, env) if isinstance(a, A.FuncCall) and a.name in ("asc", "desc")
                    else Ordering(self.fn_arg(a, env), False) for a in node.args]
        else:
            args = [self.eval(a, env) for a in node.args]
        return self.call(obj, node.name, args, node.pos)

    # -- helpers --------------------------------------------------------
    def fn_arg(self, node: A.Node, env: dict[str, Any]) -> Callable[[Any], Any]:
        """Lambdas stay lambdas; any other expression becomes `el => expr` with `.field` bound to el."""
        if isinstance(node, A.Lambda):
            return Fn(node.params, node.body, env, self)

        def implicit(el: Any) -> Any:
            out = self.eval(node, {**env, THIS: el})
            return out(el) if isinstance(out, Fn) else out

        return implicit

    @staticmethod
    def equal(a: Any, b: Any) -> bool:
        if isinstance(a, DocRef) and isinstance(b, DocRef):
            return (a.doc.coll, a.doc.id) == (b.doc.coll, b.doc.id)
        if isinstance(a, bool) != isinstance(b, bool):
            return False
        return a == b

    def member(self, obj: Any, name: str, pos: int) -> Any:
        if obj is None:
            return None
        if isinstance(obj, DocRef):
            if name in ("id", "coll", "ts"):
                return getattr(obj.doc, name)
            return obj.doc.data.get(name)
        if isinstance(obj, dict):
            return obj.get(name)
        if isinstance(obj, (list, str)) and name == "length":
            return len(obj)
        if isinstance(obj, CollRef) and name == "name":
            return obj.name
        raise FQLError("invalid_field_access", f"{type_name(obj)} has no field '{name}'", pos)

    def _expect_args(self, name: str, args: list, n: int, pos: int) -> None:
        if len(args) < n:
            raise FQLError("invalid_argument", f"{name}() expects {n} argument(s)", pos)

    def call(self, obj: Any, name: str, args: list[Any], pos: int) -> Any:
        if isinstance(obj, CollectionNamespace):
            if name == "all":
                return [{"name": k, "count": v} for k, v in self.store.collections().items()]
            if name == "byName":
                self._expect_args(name, args, 1, pos)
                return CollRef(str(args[0]))
        elif isinstance(obj, CollRef):
            return self.call_collection(obj, name, args, pos)
        elif isinstance(obj, DocRef):
            return self.call_document(obj, name, args, pos)
        elif isinstance(obj, (FSet, list)):
            return self.call_sequence(obj, name, args, pos)
        elif isinstance(obj, str):
            return self.call_string(obj, name, args, pos)
        raise FQLError("invalid_method", f"{type_name(obj)} has no method '{name}'", pos)

    def call_collection(self, coll: CollRef, name: str, args: list[Any], pos: int) -> Any:
        store = self.store
        all_docs = FSet(lambda: (DocRef(d) for d in store.scan(coll.name)))
        if name == "all":
            return all_docs
        if name in ("where", "firstWhere"):
            return self.call_sequence(all_docs, name, args, pos)
        if name == "count":
            return store.count(coll.name)
        if name == "byId":
            self._expect_args(name, args, 1, pos)
            doc = store.get(coll.name, str(args[0]))
            return DocRef(doc) if doc else None
        if name == "search":
            self._expect_args(name, args, 1, pos)
            lim = int(args[1]) if len(args) > 1 else 50
            docs = store.search(coll.name, str(args[0]), lim)
            return FSet(lambda: (DocRef(d) for d in docs))
        if name == "create":
            self._expect_args(name, args, 1, pos)
            if not isinstance(args[0], dict):
                raise FQLError("invalid_argument", "create() takes an object", pos)
            doc, _ = store.create(coll.name, to_json(args[0]))
            return DocRef(doc)
        raise FQLError("invalid_method", f"Collection has no method '{name}'", pos)

    def call_document(self, ref: DocRef, name: str, args: list[Any], pos: int) -> Any:
        if name in ("update", "replace"):
            self._expect_args(name, args, 1, pos)
            if not isinstance(args[0], dict):
                raise FQLError("invalid_argument", f"{name}() takes an object", pos)
            doc = self.store.update(ref.doc.coll, ref.doc.id, to_json(args[0]), replace=(name == "replace"))
            return DocRef(doc) if doc else None
        if name == "delete":
            self.store.delete(ref.doc.coll, ref.doc.id)
            return {"id": ref.doc.id, "coll": ref.doc.coll, "deleted": True}
        if name == "exists":
            return self.store.get(ref.doc.coll, ref.doc.id) is not None
        raise FQLError("invalid_method", f"Document has no method '{name}'", pos)

    def call_string(self, s: str, name: str, args: list[Any], pos: int) -> Any:
        arg = str(args[0]) if args else ""
        table: dict[str, Callable[[], Any]] = {
            "includes": lambda: arg in s,
            "startsWith": lambda: s.startswith(arg),
            "endsWith": lambda: s.endswith(arg),
            "toLowerCase": s.lower,
            "toUpperCase": s.upper,
            "trim": s.strip,
            "split": lambda: s.split(arg) if arg else s.split(),
            "slice": lambda: s[int(args[0]) if args else 0:int(args[1]) if len(args) > 1 else None],
        }
        if name not in table:
            raise FQLError("invalid_method", f"String has no method '{name}'", pos)
        return table[name]()

    def call_sequence(self, seq: FSet | list, name: str, args: list[Any], pos: int) -> Any:
        is_set = isinstance(seq, FSet)
        src: Callable[[], Iterator[Any]] = (lambda: iter(seq))

        def wrap(factory: Callable[[], Iterator[Any]]) -> Any:
            return FSet(factory) if is_set else list(factory())

        def int_arg() -> int:
            self._expect_args(name, args, 1, pos)
            if not isinstance(args[0], int) or isinstance(args[0], bool) or args[0] < 0:
                raise FQLError("invalid_argument", f"{name}() takes a non-negative integer", pos)
            return args[0]

        if name == "where":
            self._expect_args(name, args, 1, pos)
            f = args[0]
            return wrap(lambda: (x for x in src() if truthy(f(x))))
        if name == "map":
            self._expect_args(name, args, 1, pos)
            f = args[0]
            return wrap(lambda: (f(x) for x in src()))
        if name == "flatMap":
            self._expect_args(name, args, 1, pos)
            f = args[0]
            return wrap(lambda: (y for x in src() for y in (f(x) or [])))
        if name == "order":
            orderings: list[Ordering] = args or [Ordering(lambda x: x, False)]

            def ordered() -> Iterator[Any]:
                items = list(src())
                for o in reversed(orderings):
                    items.sort(key=lambda x, o=o: sort_key(o.key(x)), reverse=o.reverse)
                return iter(items)

            return wrap(ordered)
        if name == "take":
            n = int_arg()
            return wrap(lambda: itertools.islice(src(), n))
        if name == "drop":
            n = int_arg()
            return wrap(lambda: itertools.islice(src(), n, None))
        if name == "reverse":
            return wrap(lambda: reversed(list(src())))
        if name == "distinct":
            def distinct() -> Iterator[Any]:
                seen: list[Any] = []
                for x in src():
                    if not any(self.equal(x, s) for s in seen):
                        seen.append(x)
                        yield x
            return wrap(distinct)
        if name == "concat":
            self._expect_args(name, args, 1, pos)
            other = args[0]
            return wrap(lambda: itertools.chain(src(), iter(other)))
        if name == "first":
            return next(src(), None)
        if name == "last":
            last = None
            for x in src():
                last = x
            return last
        if name == "firstWhere":
            self._expect_args(name, args, 1, pos)
            return next((x for x in src() if truthy(args[0](x))), None)
        if name == "count":
            return sum(1 for _ in src())
        if name == "isEmpty":
            return not any(True for _ in itertools.islice(src(), 1))
        if name == "nonEmpty":
            return any(True for _ in itertools.islice(src(), 1))
        if name == "includes":
            self._expect_args(name, args, 1, pos)
            return any(self.equal(x, args[0]) for x in src())
        if name == "any":
            self._expect_args(name, args, 1, pos)
            return any(truthy(args[0](x)) for x in src())
        if name == "every":
            self._expect_args(name, args, 1, pos)
            return all(truthy(args[0](x)) for x in src())
        if name == "toArray":
            return list(src())
        if name == "toSet":
            return FSet(src)
        raise FQLError("invalid_method", f"{type_name(seq)} has no method '{name}'", pos)


def run_fql(store: Any, src: str, *, readonly: bool = False, limit: int = 1000) -> dict[str, Any]:
    """Run a query and wrap the outcome in the wire format every UI and the CLI use."""
    started = time.perf_counter()
    try:
        data = Evaluator(store, readonly=readonly, limit=limit).run(src)
        return {"ok": True, "data": data, "took_ms": round((time.perf_counter() - started) * 1000, 2)}
    except FQLError as exc:
        return {"ok": False, "error": exc.to_json(), "took_ms": round((time.perf_counter() - started) * 1000, 2)}
