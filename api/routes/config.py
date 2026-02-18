from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request

from api.auth import AuthDep
from api.deps import get_config
from engine.core.config import Config


router = APIRouter(prefix="/config", dependencies=[AuthDep])


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
    return config.model_dump(mode="json")


@router.post("/validate")
def validate_config(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = _validate_config_dict(payload)
    return {"ok": True, "config": cfg.model_dump(mode="json")}


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
