from __future__ import annotations

from dataclasses import dataclass

from querybook.core.fql.errors import FQLError

SYMBOLS = ("=>", "==", "!=", "<=", ">=", "&&", "||", "<", ">", "!", "+", "-", "*", "/", "%",
           ".", ",", "(", ")", "[", "]", "{", "}", ":", ";", "=")
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "/": "/", "\\": "\\", '"': '"', "'": "'"}


@dataclass(frozen=True)
class Token:
    kind: str  # num | str | ident | op | eof
    value: object
    pos: int
    nl: bool = False  # a newline precedes this token (ends a `let` value before `[`, `(` or `{`)


def tokenize(src: str) -> list[Token]:
    toks: list[Token] = []
    i, n = 0, len(src)
    nl = False

    def push(kind: str, value: object, pos: int) -> None:
        nonlocal nl
        toks.append(Token(kind, value, pos, nl))
        nl = False

    while i < n:
        ch = src[i]
        if ch.isspace():
            nl = nl or ch == "\n"
            i += 1
            continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if ch.isdigit():
            start = i
            while i < n and (src[i].isdigit() or src[i] == "_"):
                i += 1
            is_float = False
            if i + 1 < n and src[i] == "." and src[i + 1].isdigit():
                is_float = True
                i += 1
                while i < n and src[i].isdigit():
                    i += 1
            if i < n and src[i] in "eE":
                j = i + 1
                if j < n and src[j] in "+-":
                    j += 1
                if j < n and src[j].isdigit():
                    is_float = True
                    i = j
                    while i < n and src[i].isdigit():
                        i += 1
            text = src[start:i].replace("_", "")
            push("num", float(text) if is_float else int(text), start)
            continue
        if ch in "\"'":
            quote, start, i = ch, i, i + 1
            buf: list[str] = []
            while True:
                if i >= n:
                    raise FQLError("syntax_error", "Unterminated string", start)
                c = src[i]
                if c == quote:
                    i += 1
                    break
                if c == "\\":
                    if i + 1 >= n:
                        raise FQLError("syntax_error", "Unterminated escape", i)
                    e = src[i + 1]
                    if e == "u":
                        hexpart = src[i + 2:i + 6]
                        try:
                            buf.append(chr(int(hexpart, 16)))
                        except ValueError:
                            raise FQLError("syntax_error", "Bad \\u escape", i) from None
                        i += 6
                        continue
                    if e not in ESCAPES:
                        raise FQLError("syntax_error", f"Unknown escape \\{e}", i)
                    buf.append(ESCAPES[e])
                    i += 2
                    continue
                buf.append(c)
                i += 1
            push("str", "".join(buf), start)
            continue
        if ch.isalpha() or ch == "_":
            start = i
            while i < n and (src[i].isalnum() or src[i] == "_"):
                i += 1
            push("ident", src[start:i], start)
            continue
        for sym in SYMBOLS:
            if src.startswith(sym, i):
                push("op", sym, i)
                i += len(sym)
                break
        else:
            raise FQLError("syntax_error", f"Unexpected character {ch!r}", i)
    push("eof", None, n)
    return toks
