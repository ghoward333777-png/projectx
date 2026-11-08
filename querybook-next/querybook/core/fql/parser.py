"""Recursive-descent FQL parser.

program    := ("let" IDENT "=" expr ";"?)* expr
expr       := or ; or := and ("||" and)* ; and := cmp ("&&" cmp)*
cmp        := add (("=="|"!="|"<"|"<="|">"|">=") add)?
add        := mul (("+"|"-") mul)* ; mul := unary (("*"|"/"|"%") unary)*
unary      := ("!"|"-") unary | postfix
postfix    := primary ("." IDENT ["(" args ")"] | "[" expr "]" | "{" projection "}")*
              (a "[", "{" or call "(" that starts a new line begins a new expression instead)
primary    := literal | IDENT | IDENT "(" args ")" | lambda | "." IDENT ("." IDENT)*
            | "(" expr ")" | "[" items "]" | "{" pairs "}"
lambda     := IDENT "=>" expr | "(" IDENT ("," IDENT)* ")" "=>" expr
"""

from __future__ import annotations

from querybook.core.fql import ast as A
from querybook.core.fql.errors import FQLError
from querybook.core.fql.lexer import Token, tokenize

COMPARE = ("==", "!=", "<", "<=", ">", ">=")


class Parser:
    def __init__(self, src: str) -> None:
        self.toks = tokenize(src)
        self.i = 0

    # helpers
    def peek(self, k: int = 0) -> Token:
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def is_op(self, value: str, k: int = 0) -> bool:
        t = self.peek(k)
        return t.kind == "op" and t.value == value

    def advance(self) -> Token:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect_op(self, value: str) -> Token:
        if not self.is_op(value):
            t = self.peek()
            found = "end of query" if t.kind == "eof" else repr(t.value)
            raise FQLError("syntax_error", f"Expected '{value}' but found {found}", t.pos)
        return self.advance()

    def expect_ident(self) -> Token:
        t = self.peek()
        if t.kind != "ident":
            raise FQLError("syntax_error", "Expected a name", t.pos)
        return self.advance()

    # grammar
    def program(self) -> A.Node:
        node = self.statements()
        if self.peek().kind != "eof":
            t = self.peek()
            raise FQLError("syntax_error", f"Unexpected {t.value!r}", t.pos)
        return node

    def statements(self) -> A.Node:
        t = self.peek()
        if t.kind == "ident" and t.value == "let":
            self.advance()
            name = self.expect_ident().value
            self.expect_op("=")
            value = self.expr()
            if self.is_op(";"):
                self.advance()
            return A.Let(t.pos, name, value, self.statements())
        return self.expr()

    def expr(self) -> A.Node:
        return self.or_()

    def or_(self) -> A.Node:
        left = self.and_()
        while self.is_op("||"):
            pos = self.advance().pos
            left = A.Binary(pos, "||", left, self.and_())
        return left

    def and_(self) -> A.Node:
        left = self.cmp()
        while self.is_op("&&"):
            pos = self.advance().pos
            left = A.Binary(pos, "&&", left, self.cmp())
        return left

    def cmp(self) -> A.Node:
        left = self.add()
        t = self.peek()
        if t.kind == "op" and t.value in COMPARE:
            self.advance()
            return A.Binary(t.pos, t.value, left, self.add())
        return left

    def add(self) -> A.Node:
        left = self.mul()
        while self.peek().kind == "op" and self.peek().value in ("+", "-"):
            t = self.advance()
            left = A.Binary(t.pos, t.value, left, self.mul())
        return left

    def mul(self) -> A.Node:
        left = self.unary()
        while self.peek().kind == "op" and self.peek().value in ("*", "/", "%"):
            t = self.advance()
            left = A.Binary(t.pos, t.value, left, self.unary())
        return left

    def unary(self) -> A.Node:
        t = self.peek()
        if t.kind == "op" and t.value in ("!", "-"):
            self.advance()
            return A.Unary(t.pos, t.value, self.unary())
        return self.postfix(self.primary())

    def args(self) -> tuple[A.Node, ...]:
        self.expect_op("(")
        out: list[A.Node] = []
        while not self.is_op(")"):
            out.append(self.expr())
            if not self.is_op(","):
                break
            self.advance()
        self.expect_op(")")
        return tuple(out)

    def postfix(self, node: A.Node) -> A.Node:
        while True:
            if self.is_op("."):
                self.advance()
                name_tok = self.expect_ident()
                if self.is_op("("):
                    node = A.MethodCall(name_tok.pos, node, name_tok.value, self.args())
                else:
                    node = A.Member(name_tok.pos, node, name_tok.value)
            elif self.is_op("[") and not self.peek().nl:
                pos = self.advance().pos
                idx = self.expr()
                self.expect_op("]")
                node = A.Index(pos, node, idx)
            elif self.is_op("{") and not self.peek().nl:
                node = A.Projection(self.peek().pos, node, self.projection())
            else:
                return node

    def projection(self) -> tuple[tuple[str, A.Node | None], ...]:
        self.expect_op("{")
        fields: list[tuple[str, A.Node | None]] = []
        while not self.is_op("}"):
            t = self.peek()
            if t.kind not in ("ident", "str"):
                raise FQLError("syntax_error", "Expected a field name in projection", t.pos)
            self.advance()
            if self.is_op(":"):
                self.advance()
                fields.append((t.value, self.expr()))
            else:
                fields.append((t.value, None))
            if not self.is_op(","):
                break
            self.advance()
        self.expect_op("}")
        return tuple(fields)

    def lambda_ahead(self) -> bool:
        if not self.is_op("("):
            return False
        k = 1
        while True:
            if self.peek(k).kind != "ident":
                return self.is_op(")", k) and self.is_op("=>", k + 1)
            k += 1
            if self.is_op(")", k):
                return self.is_op("=>", k + 1)
            if not self.is_op(",", k):
                return False
            k += 1

    def primary(self) -> A.Node:
        t = self.peek()
        if t.kind in ("num", "str"):
            self.advance()
            return A.Literal(t.pos, t.value)
        if t.kind == "ident":
            if t.value in ("true", "false", "null"):
                self.advance()
                return A.Literal(t.pos, {"true": True, "false": False, "null": None}[t.value])
            if self.is_op("=>", 1):
                self.advance()
                self.advance()
                return A.Lambda(t.pos, (t.value,), self.expr())
            self.advance()
            if self.is_op("(") and not self.peek().nl:
                return A.FuncCall(t.pos, t.value, self.args())
            return A.Ident(t.pos, t.value)
        if self.is_op("."):
            pos = self.advance().pos
            path = [self.expect_ident().value]
            while self.is_op(".") and self.peek(1).kind == "ident" and not self.is_op("(", 2):
                self.advance()
                path.append(self.advance().value)
            return A.FieldPath(pos, tuple(path))
        if self.is_op("("):
            if self.lambda_ahead():
                self.advance()
                params: list[str] = []
                while not self.is_op(")"):
                    params.append(self.expect_ident().value)
                    if self.is_op(","):
                        self.advance()
                self.expect_op(")")
                self.expect_op("=>")
                return A.Lambda(t.pos, tuple(params), self.expr())
            self.advance()
            inner = self.expr()
            self.expect_op(")")
            return inner
        if self.is_op("["):
            self.advance()
            items: list[A.Node] = []
            while not self.is_op("]"):
                items.append(self.expr())
                if not self.is_op(","):
                    break
                self.advance()
            self.expect_op("]")
            return A.ArrayLit(t.pos, tuple(items))
        if self.is_op("{"):
            self.advance()
            pairs: list[tuple[str, A.Node]] = []
            while not self.is_op("}"):
                k = self.peek()
                if k.kind not in ("ident", "str"):
                    raise FQLError("syntax_error", "Expected an object key", k.pos)
                self.advance()
                self.expect_op(":")
                pairs.append((k.value, self.expr()))
                if not self.is_op(","):
                    break
                self.advance()
            self.expect_op("}")
            return A.ObjectLit(t.pos, tuple(pairs))
        found = "end of query" if t.kind == "eof" else repr(t.value)
        raise FQLError("syntax_error", f"Unexpected {found}", t.pos)


def parse(src: str) -> A.Node:
    if not src or not src.strip():
        raise FQLError("syntax_error", "Empty query", 0)
    return Parser(src).program()
