"""engine.core.paths – Single source of truth for b1e55ed filesystem paths.

All operator data lives under B1E55ED_DIR (~/.b1e55ed).
"""

from __future__ import annotations

import os
from pathlib import Path


# Borges imagined a library containing every possible book.
# We needed only one directory. But we kept deriving it in twelve places.
# Now there is one function. The Library of Babel, collapsed to a single shelf.
def b1e55ed_dir() -> Path:
    """Return the operator data root: ~/.b1e55ed."""
    return Path.home() / ".b1e55ed"


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


# /etc, /var, /tmp — the ancients understood:
# name the directory once, reference it everywhere.
def secrets_dir() -> Path:
    """Return the secrets directory: ~/.b1e55ed/secrets."""
    return b1e55ed_dir() / "secrets"


def config_dir() -> Path:
    """Return the config directory: ~/.b1e55ed/config."""
    return b1e55ed_dir() / "config"


_DB_FILENAME = "brain.db"


def get_db_path(cfg=None, *, base_data_dir: Path | None = None) -> Path:
    """Single source of truth for the brain.db path.

    Priority:
    1. B1E55ED_DATA_DIR env var  →  $B1E55ED_DATA_DIR/brain.db
    2. cfg.data_dir if a Config object is supplied
    3. base_data_dir if explicitly provided (caller-supplied data directory)
    4. ~/.b1e55ed/data/brain.db  (default)

    Use this everywhere instead of constructing the path inline.
    """
    env_data = os.environ.get("B1E55ED_DATA_DIR")
    if env_data:
        return Path(env_data) / _DB_FILENAME

    if cfg is not None:
        cfg_data_dir = getattr(cfg, "data_dir", None)
        if cfg_data_dir is not None:
            p = Path(cfg_data_dir)
            if not p.is_absolute():
                p = b1e55ed_dir() / p
            return p / _DB_FILENAME

    if base_data_dir is not None:
        return Path(base_data_dir) / _DB_FILENAME

    return data_dir() / _DB_FILENAME
