from __future__ import annotations


class FQLError(Exception):
    """Every FQL failure carries a stable code (for UIs/Rust parity) and a source offset."""

    def __init__(self, code: str, message: str, pos: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.pos = pos

    def to_json(self) -> dict:
        return {"code": self.code, "message": self.message, "pos": self.pos}
