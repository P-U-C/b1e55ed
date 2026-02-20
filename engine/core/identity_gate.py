"""engine.core.identity_gate

Enforces forged identity as a prerequisite for system access.
No identity = no access. The work is the gate.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ForgedIdentity:
    address: str
    node_id: str
    forged_at: int
    candidates_evaluated: int
    elapsed_ms: int


def load_identity(repo_root: Path) -> ForgedIdentity | None:
    """Load forged identity from .b1e55ed/identity.json. Returns None if not forged."""
    identity_path = repo_root / ".b1e55ed" / "identity.json"
    if not identity_path.exists():
        return None
    try:
        data = json.loads(identity_path.read_text())
        return ForgedIdentity(
            address=data["address"],
            node_id=data["node_id"],
            forged_at=data.get("forged_at", 0),
            candidates_evaluated=data.get("candidates_evaluated", 0),
            elapsed_ms=data.get("elapsed_ms", 0),
        )
    except (KeyError, json.JSONDecodeError, OSError):
        return None


def require_identity(repo_root: Path) -> ForgedIdentity:
    """Load identity or raise with clear message."""
    identity = load_identity(repo_root)
    if identity is None:
        raise IdentityRequired
    return identity


def is_dev_mode() -> bool:
    """Check if dev mode bypasses the gate."""
    return os.environ.get("B1E55ED_DEV_MODE", "").lower() in ("1", "true", "yes")


class IdentityRequired(Exception):
    """Raised when a forged identity is required but not found."""

    def __init__(self) -> None:
        super().__init__("Identity required. Run `b1e55ed identity forge` first.")
