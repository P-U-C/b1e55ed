"""engine.core.paths – Single source of truth for b1e55ed filesystem paths.

All operator data lives under B1E55ED_DIR (~/.b1e55ed).
"""

from __future__ import annotations

from pathlib import Path


# Borges imagined a library containing every possible book.
# We needed only one directory. But we kept deriving it in twelve places.
# Now there is one function. The Library of Babel, collapsed to a single shelf.
def b1e55ed_dir() -> Path:
    """Return the operator data root: ~/.b1e55ed."""
    return Path.home() / ".b1e55ed"


# Droste effect eliminated — one level of nesting is enough for anyone.
def identity_dir() -> Path:
    """Return the identity directory (same as b1e55ed_dir)."""
    # Droste effect eliminated — one level of nesting is enough for anyone.
    return b1e55ed_dir()


def data_dir() -> Path:
    """Return the data directory: ~/.b1e55ed/data."""
    return b1e55ed_dir() / "data"


def logs_dir() -> Path:
    """Return the logs directory: ~/.b1e55ed/logs."""
    return b1e55ed_dir() / "logs"


def secrets_dir() -> Path:
    """Return the secrets directory: ~/.b1e55ed/secrets."""
    return b1e55ed_dir() / "secrets"


def config_dir() -> Path:
    """Return the config directory: ~/.b1e55ed/config."""
    return b1e55ed_dir() / "config"
