from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from api.auth import AuthDep
from api.deps import get_config
from api.errors import B1e55edError
from engine.core.bundle_packs import bundle_template_from_pack, get_bundle_pack, list_bundle_packs
from engine.core.config import Config, UniverseBundle
from engine.core.paths import config_dir

router = APIRouter(prefix="/universe", dependencies=[AuthDep])

_ID_RE = re.compile(r"[^a-z0-9]+")


class UniverseBundlesResponse(BaseModel):
    items: list[UniverseBundle] = Field(default_factory=list)
    total: int = 0


class UniverseBundlePacksResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0


class CreateBundleRequest(BaseModel):
    id: str | None = None
    pack_id: str | None = None
    name: str | None = None
    symbols: list[str] | None = None
    tags: list[str] | None = None
    asset_class: str | None = None
    venue: str | None = None
    enabled: bool = True
    source: Literal["wizard", "user", "system"] = "user"

    @field_validator("pack_id", mode="before")
    @classmethod
    def _normalize_pack_id(cls, v: Any) -> str | None:
        text = str(v or "").strip().lower()
        return text or None


class UpdateBundleRequest(BaseModel):
    name: str | None = None
    symbols: list[str] | None = None
    tags: list[str] | None = None
    asset_class: str | None = None
    venue: str | None = None
    enabled: bool | None = None


class ActiveUniverseResponse(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    count: int = 0
    fallback_to_symbols: bool = True
    bundles: list[UniverseBundle] = Field(default_factory=list)
    enabled_bundle_ids: list[str] = Field(default_factory=list)
    asset_classes: list[str] = Field(default_factory=list)
    venues: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    asset_class_symbols: dict[str, list[str]] = Field(default_factory=dict)
    venue_symbols: dict[str, list[str]] = Field(default_factory=dict)
    tag_symbols: dict[str, list[str]] = Field(default_factory=dict)


def _config_path() -> Path:
    path = config_dir() / "user.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _save_config(cfg: Config, *, path: Path) -> None:
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False), encoding="utf-8")


def _slugify_bundle_id(raw: str) -> str:
    slug = _ID_RE.sub("-", raw.lower()).strip("-")
    return slug or "bundle"


def _alloc_bundle_id(*, candidate: str, existing: set[str]) -> str:
    base = _slugify_bundle_id(candidate)
    if base not in existing:
        return base
    i = 2
    while f"{base}-{i}" in existing:
        i += 1
    return f"{base}-{i}"


def _update_config(request: Request, config: Config, bundles: list[UniverseBundle]) -> Config:
    next_universe = config.universe.model_copy(update={"bundles": bundles})
    next_cfg = config.model_copy(update={"universe": next_universe})
    _save_config(next_cfg, path=_config_path())
    request.app.state.config = next_cfg
    return next_cfg


def _active_payload(config: Config) -> ActiveUniverseResponse:
    universe = config.universe
    bundles = list(universe.bundles)
    enabled = [b for b in bundles if b.enabled]

    active_symbols = universe.active_symbols()
    enabled_bundle_symbols = [s for b in enabled for s in b.symbols]
    fallback_to_symbols = len(universe.normalize_symbols(enabled_bundle_symbols)) == 0

    asset_class_map: dict[str, list[str]] = defaultdict(list)
    venue_map: dict[str, list[str]] = defaultdict(list)
    tag_map: dict[str, list[str]] = defaultdict(list)

    for bundle in enabled:
        if bundle.asset_class:
            asset_class_map[bundle.asset_class].extend(bundle.symbols)
        if bundle.venue:
            venue_map[bundle.venue].extend(bundle.symbols)
        for tag in bundle.tags:
            if tag:
                tag_map[tag].extend(bundle.symbols)

    asset_class_symbols = {k: universe.normalize_symbols(v) for k, v in asset_class_map.items() if k}
    venue_symbols = {k: universe.normalize_symbols(v) for k, v in venue_map.items() if k}
    tag_symbols = {k: universe.normalize_symbols(v) for k, v in tag_map.items() if k}

    return ActiveUniverseResponse(
        symbols=active_symbols,
        count=len(active_symbols),
        fallback_to_symbols=fallback_to_symbols,
        bundles=bundles,
        enabled_bundle_ids=[b.id for b in enabled],
        asset_classes=sorted(asset_class_symbols.keys()),
        venues=sorted(venue_symbols.keys()),
        tags=sorted(tag_symbols.keys()),
        asset_class_symbols=asset_class_symbols,
        venue_symbols=venue_symbols,
        tag_symbols=tag_symbols,
    )


@router.get("/packs", response_model=UniverseBundlePacksResponse)
def list_packs() -> UniverseBundlePacksResponse:
    items = list_bundle_packs()
    return UniverseBundlePacksResponse(items=items, total=len(items))


@router.get("/bundles", response_model=UniverseBundlesResponse)
def list_bundles(config: Config = Depends(get_config)) -> UniverseBundlesResponse:
    items = list(config.universe.bundles)
    return UniverseBundlesResponse(items=items, total=len(items))


@router.post("/bundles", response_model=UniverseBundle)
def create_bundle(
    request: Request,
    payload: CreateBundleRequest,
    config: Config = Depends(get_config),
) -> UniverseBundle:
    bundles = list(config.universe.bundles)
    ids = {b.id for b in bundles}

    name = str(payload.name or "").strip()
    symbols = list(payload.symbols or [])
    tags = list(payload.tags or [])
    asset_class = str(payload.asset_class or "").strip() or "crypto"
    venue = str(payload.venue or "").strip() or "global"

    if payload.pack_id:
        pack = get_bundle_pack(payload.pack_id)
        if pack is None:
            raise B1e55edError(
                code="universe.bundle_pack_not_found",
                message="Bundle pack not found",
                status=404,
                pack_id=payload.pack_id,
            )

        template = bundle_template_from_pack(
            payload.pack_id,
            source=payload.source,
            enabled=payload.enabled,
            name=name or None,
            symbols=symbols or None,
            tags=tags or None,
            asset_class=asset_class if payload.asset_class is not None else None,
            venue=venue if payload.venue is not None else None,
        )
        if template is None:
            raise B1e55edError(
                code="universe.bundle_pack_not_found",
                message="Bundle pack not found",
                status=404,
                pack_id=payload.pack_id,
            )

        name = str(template.get("name") or "").strip()
        symbols = list(template.get("symbols") or [])
        tags = list(template.get("tags") or [])
        asset_class = str(template.get("asset_class") or "crypto")
        venue = str(template.get("venue") or "global")

    if not name:
        raise B1e55edError(code="universe.bundle_name_required", message="Bundle name is required", status=400)
    if not symbols:
        raise B1e55edError(code="universe.bundle_symbols_required", message="Bundle symbols are required", status=400)

    candidate = payload.id.strip() if payload.id else (payload.pack_id or name)
    bundle_id = _alloc_bundle_id(candidate=candidate, existing=ids)

    new_bundle = UniverseBundle(
        id=bundle_id,
        name=name,
        symbols=symbols,
        tags=tags,
        asset_class=asset_class,
        venue=venue,
        enabled=payload.enabled,
        source=payload.source,
    )

    _update_config(request, config, bundles + [new_bundle])
    return new_bundle


@router.patch("/bundles/{bundle_id}", response_model=UniverseBundle)
def update_bundle(
    bundle_id: str,
    request: Request,
    payload: UpdateBundleRequest,
    config: Config = Depends(get_config),
) -> UniverseBundle:
    bundles = list(config.universe.bundles)
    idx = next((i for i, b in enumerate(bundles) if b.id == bundle_id), -1)
    if idx < 0:
        raise B1e55edError(code="universe.bundle_not_found", message="Bundle not found", status=404, bundle_id=bundle_id)

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return bundles[idx]

    updated = bundles[idx].model_copy(update=updates)
    bundles[idx] = updated
    _update_config(request, config, bundles)
    return updated


@router.delete("/bundles/{bundle_id}")
def delete_bundle(
    bundle_id: str,
    request: Request,
    config: Config = Depends(get_config),
) -> dict[str, object]:
    bundles = list(config.universe.bundles)
    kept = [b for b in bundles if b.id != bundle_id]
    if len(kept) == len(bundles):
        raise B1e55edError(code="universe.bundle_not_found", message="Bundle not found", status=404, bundle_id=bundle_id)

    _update_config(request, config, kept)
    return {"ok": True, "deleted": bundle_id}


@router.get("/active", response_model=ActiveUniverseResponse)
def get_active_universe(config: Config = Depends(get_config)) -> ActiveUniverseResponse:
    return _active_payload(config)
