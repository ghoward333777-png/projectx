"""FQL syntax tree. One frozen dataclass per node kind == one Rust enum variant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Node:
    pos: int


@dataclass(frozen=True)
class Literal(Node):
    value: Any


@dataclass(frozen=True)
class Ident(Node):
    name: str


@dataclass(frozen=True)
class FieldPath(Node):
    """`.a.b` — field of the implicit element inside where()/map()/order()."""
    path: tuple[str, ...]


@dataclass(frozen=True)
class Member(Node):
    obj: Node
    name: str


@dataclass(frozen=True)
class MethodCall(Node):
    obj: Node
    name: str
    args: tuple[Node, ...]


@dataclass(frozen=True)
class FuncCall(Node):
    name: str
    args: tuple[Node, ...]


@dataclass(frozen=True)
class Index(Node):
    obj: Node
    index: Node


@dataclass(frozen=True)
class Unary(Node):
    op: str
    operand: Node


@dataclass(frozen=True)
class Binary(Node):
    op: str
    left: Node
    right: Node


@dataclass(frozen=True)
class Lambda(Node):
    params: tuple[str, ...]
    body: Node


@dataclass(frozen=True)
class ArrayLit(Node):
    items: tuple[Node, ...]


@dataclass(frozen=True)
class ObjectLit(Node):
    pairs: tuple[tuple[str, Node], ...]


@dataclass(frozen=True)
class Projection(Node):
    obj: Node
    fields: tuple[tuple[str, Node | None], ...]


@dataclass(frozen=True)
class Let(Node):
    name: str
    value: Node
    body: Node
