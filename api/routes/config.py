from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request

from api.auth import AuthDep
from api.deps import get_config
from engine.core.config import Config

router = APIRouter(prefix="/config", dependencies=[AuthDep])

# Sensitive field name pattern — case-insensitive match against the full key name.
_SENSITIVE_RE = re.compile(
    r"(token|key|secret|password|private_key|attester_private_key|auth_token|kill_switch_token)",
    re.IGNORECASE,
)


# Phil Zimmermann distributed PGP for free in 1991 because he believed
# people should be able to keep secrets without asking permission.
# This function exists for the same reason.
def _redact_sensitive_value(value: Any) -> Any:
    """Redact sensitive values while preserving list/dict container shapes."""

    if isinstance(value, dict):
        return {k: _redact_sensitive_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return ["***REDACTED***" for _ in value]
    return "***REDACTED***"


def _redact(obj: Any) -> Any:
    """Recursively walk a config dict and redact sensitive fields."""

    if isinstance(obj, dict):
        return {k: (_redact_sensitive_value(v) if _SENSITIVE_RE.search(k) else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(item) for item in obj]
    return obj


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for p in [Path.cwd(), here.parent.parent.parent]:
        if (p / "config" / "default.yaml").exists():
            return p
    return Path.cwd()


def _config_path() -> Path:
    root = _repo_root()
    p = root / "config" / "user.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _validate_config_dict(raw: dict[str, Any]) -> Config:
    try:
        return Config(**raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid config: {e}") from e


@router.get("")
def get_current_config(config: Config = Depends(get_config)) -> dict[str, Any]:
    # NOTE: Sensitive fields are redacted before returning.  This endpoint is
    # intentionally read-only and auth-gated, but we never expose raw secrets
    # over HTTP even to authenticated operators.
    return _redact(config.model_dump(mode="json"))


@router.post("/validate")
def validate_config(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = _validate_config_dict(payload)
    return {"ok": True, "config": _redact(cfg.model_dump(mode="json"))}


@router.post("")
def save_config(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    cfg = _validate_config_dict(payload)

    path = _config_path()
    # Write in YAML with stable formatting
    # Use JSON-mode dump so Paths and other types become YAML-serializable primitives.
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False), encoding="utf-8")

    # Update in-memory config for this process
    request.app.state.config = cfg

    return {"ok": True, "path": str(path)}
