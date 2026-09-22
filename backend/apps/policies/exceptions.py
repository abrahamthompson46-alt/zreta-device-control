from __future__ import annotations


class PolicyError(Exception):
    """Domain error for policy validation and lifecycle operations."""

    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code
