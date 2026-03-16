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
def _load_config() -> Config:
    from engine.core.paths import config_dir

    user_path = config_dir() / "user.yaml"
    if user_path.exists():
        return Config.from_yaml(user_path)
    return Config.from_repo_defaults(Path(__file__).resolve().parent.parent)


def get_config(request: Request) -> Config:
    cfg = getattr(request.app.state, "config", None)
    return cfg or _load_config()


def get_db(request: Request) -> Database:
    db = getattr(request.app.state, "db", None)
    if db is not None:
        return db
    from engine.core.paths import get_db_path

    return Database(get_db_path())


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
    row = db.fetchone(
        "SELECT payload, ts FROM events WHERE type = ? ORDER BY ts DESC LIMIT 1",
        ("system.kill_switch.v1",),
    )
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


def get_publisher(request: Request) -> object | None:
    """Return a bound GitHub publisher callable, or None if not configured.

    Supports both static PAT (publish.github.token) and GitHub App auth
    (publish.github.app_id + B1E55ED_GITHUB_APP_KEY env var).
    Fail-open — returns None on failure rather than raising.
    """
    from engine.config.github_app_defaults import COMMUNITY_APP_ID, COMMUNITY_REPO
    from engine.integrations.github_publish import make_publisher

    cfg = get_config(request)
    pub_cfg = cfg.publish.github
    has_token = bool(pub_cfg.token)
    has_app = int(pub_cfg.app_id or 0) > 0

    # Fall back to baked-in community app constants if config has app_id: 0
    if not has_app and COMMUNITY_APP_ID > 0:
        has_app = True

    if not has_token and not has_app:
        return None

    app_auth = None
    if has_app:
        try:
            from engine.integrations.github_app import GitHubAppAuth

            app_auth = GitHubAppAuth.from_env()
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("get_publisher: GitHubAppAuth.from_env() failed: %s", e)
            # If app auth fails and no token, bail
            if not has_token:
                return None

    return make_publisher(
        owner=pub_cfg.owner,
        repo=pub_cfg.repo or COMMUNITY_REPO,
        token=str(pub_cfg.token or ""),
        labels=pub_cfg.labels,
        app_auth=app_auth,
    )
