from __future__ import annotations

import contextlib
from functools import lru_cache
from pathlib import Path

from fastapi import Request

from engine.brain.kill_switch import KillSwitch
from engine.core.config import Config
from engine.core.database import Database
from engine.execution.karma import KarmaEngine
from engine.producers import registry as producer_registry
from engine.security import ensure_identity


@lru_cache
def _repo_root() -> Path:
    # Assume running from repo root (uvicorn started there). Fallback to parent of this file.
    here = Path(__file__).resolve()
    for p in [Path.cwd(), here.parent.parent]:
        if (p / "config" / "default.yaml").exists():
            return p
    return Path.cwd()


@lru_cache
def _load_config() -> Config:
    root = _repo_root()
    user_path = root / "config" / "user.yaml"
    if user_path.exists():
        return Config.from_yaml(user_path)
    return Config.from_repo_defaults(root)


def get_config(request: Request) -> Config:
    cfg = getattr(request.app.state, "config", None)
    return cfg or _load_config()


def get_db(request: Request) -> Database:
    db = getattr(request.app.state, "db", None)
    if db is not None:
        return db
    root = _repo_root()
    return Database(root / "data" / "brain.db")


def get_registry(request: Request):
    reg = getattr(request.app.state, "registry", None)
    return reg or producer_registry


def get_kill_switch(request: Request) -> KillSwitch:
    ks = getattr(request.app.state, "kill_switch", None)
    if ks is not None:
        return ks
    ks = KillSwitch(config=get_config(request), db=get_db(request))
    # Rehydrate level from last kill-switch event (best-effort).
    db = get_db(request)
    row = db.conn.execute(
        "SELECT payload, ts FROM events WHERE type = ? ORDER BY ts DESC LIMIT 1",
        ("system.kill_switch.v1",),
    ).fetchone()
    if row is not None:
        import json

        payload = json.loads(str(row[0]))
        with contextlib.suppress(Exception):
            ks.reset(level=int(payload.get("level", 0)))
    return ks


def get_karma(request: Request) -> KarmaEngine:
    k = getattr(request.app.state, "karma", None)
    if k is not None:
        return k

    # API uses persisted identity (same as CLI) for consistent audit trail
    identity_handle = ensure_identity()
    return KarmaEngine(config=get_config(request), db=get_db(request), identity=identity_handle.identity)
