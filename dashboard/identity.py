from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from engine.core.config import Config


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _identity_path() -> Path:
    override = os.getenv("B1E55ED_IDENTITY_PATH")
    if override:
        return Path(override)
    return _repo_root() / ".b1e55ed" / "identity.json"


@dataclass(frozen=True)
class ForgedIdentity:
    address: str
    node_id: str
    forged_at: str
    candidates_evaluated: int | None


@dataclass(frozen=True)
class EasStatus:
    enabled: bool
    uid: str | None
    schema: str | None
    attester: str | None
    verified: bool | None


def _load_identity() -> ForgedIdentity | None:
    path = _identity_path()
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text())
    except Exception:
        return None

    if not isinstance(raw, dict):
        return None

    address = str(raw.get("address") or raw.get("wallet") or "")
    node_id = str(raw.get("node_id") or "")
    forged_at = str(raw.get("forged_at") or raw.get("created_at") or "")

    candidates = raw.get("candidates_evaluated")
    candidates_evaluated: int | None
    try:
        candidates_evaluated = int(candidates) if candidates is not None else None
    except Exception:
        candidates_evaluated = None

    if not address and not node_id:
        return None

    return ForgedIdentity(
        address=address or "—",
        node_id=node_id or "—",
        forged_at=forged_at or "—",
        candidates_evaluated=candidates_evaluated,
    )


def _eas_status(cfg: Config) -> EasStatus:
    enabled = bool(getattr(cfg.eas, "enabled", False))
    schema_uid = str(getattr(cfg.eas, "schema_uid", "") or "")

    return EasStatus(
        enabled=enabled,
        uid=None,
        schema=schema_uid or None,
        attester=None,
        verified=None,
    )


def register(app: FastAPI, templates: Jinja2Templates) -> None:
    @app.get("/identity", response_class=HTMLResponse)
    def identity_page(request: Request) -> HTMLResponse:
        identity = _load_identity()
        cfg = Config.from_repo_defaults(repo_root=_repo_root())
        eas = _eas_status(cfg)

        return templates.TemplateResponse(
            "identity.html",
            {
                "request": request,
                "active_page": "identity",
                "kill_switch_level": 0,
                "regime": "transition",
                "identity": identity,
                "eas": eas,
            },
        )
