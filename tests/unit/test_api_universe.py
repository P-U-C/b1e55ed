from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from api.main import create_app
from engine.core.database import Database
from tests.unit._api_test_client import make_client


@pytest.mark.anyio
async def test_universe_bundle_crud_and_active_resolution(temp_dir: Path, test_config, monkeypatch: pytest.MonkeyPatch):
    home = temp_dir / "home"
    monkeypatch.setenv("HOME", str(home))

    cfg = test_config.model_copy(
        update={
            "api": test_config.api.model_copy(update={"auth_token": "secret"}),
            "universe": test_config.universe.model_copy(update={"symbols": ["BTC", "ETH"], "bundles": []}),
        }
    )

    db = Database(temp_dir / "brain-universe.db")
    app = create_app()
    app.state.config = cfg
    app.state.db = db

    headers = {"Authorization": "Bearer secret"}
    async with make_client(app) as ac:
        base_active = await ac.get("/api/v1/universe/active", headers=headers)
        assert base_active.status_code == 200
        js = base_active.json()
        assert js["symbols"] == ["BTC", "ETH"]
        assert js["fallback_to_symbols"] is True

        add_crypto = await ac.post(
            "/api/v1/universe/bundles",
            headers=headers,
            json={
                "name": "Crypto Core",
                "symbols": ["SOL", "BTC"],
                "tags": ["core"],
                "asset_class": "crypto",
                "venue": "global",
                "enabled": True,
                "source": "user",
            },
        )
        assert add_crypto.status_code == 200, add_crypto.text
        b1 = add_crypto.json()
        assert b1["id"] == "crypto-core"

        add_tradfi = await ac.post(
            "/api/v1/universe/bundles",
            headers=headers,
            json={
                "name": "TradFi Starter",
                "symbols": ["SPY"],
                "asset_class": "tradfi",
                "venue": "nyse",
                "enabled": True,
                "source": "user",
            },
        )
        assert add_tradfi.status_code == 200, add_tradfi.text
        b2 = add_tradfi.json()

        bundles = await ac.get("/api/v1/universe/bundles", headers=headers)
        assert bundles.status_code == 200
        bundles_js = bundles.json()
        assert bundles_js["total"] == 2

        active_after_add = await ac.get("/api/v1/universe/active", headers=headers)
        assert active_after_add.status_code == 200
        active_js = active_after_add.json()
        assert active_js["symbols"] == ["SOL", "BTC", "SPY"]
        assert active_js["fallback_to_symbols"] is False
        assert active_js["asset_class_symbols"]["crypto"] == ["SOL", "BTC"]
        assert active_js["asset_class_symbols"]["tradfi"] == ["SPY"]
        assert active_js["tags"] == ["core"]
        assert active_js["tag_symbols"]["core"] == ["SOL", "BTC"]

        disable_crypto = await ac.patch(
            f"/api/v1/universe/bundles/{b1['id']}",
            headers=headers,
            json={"enabled": False},
        )
        assert disable_crypto.status_code == 200
        assert disable_crypto.json()["enabled"] is False

        active_after_disable = await ac.get("/api/v1/universe/active", headers=headers)
        assert active_after_disable.status_code == 200
        assert active_after_disable.json()["symbols"] == ["SPY"]

        delete_tradfi = await ac.delete(f"/api/v1/universe/bundles/{b2['id']}", headers=headers)
        assert delete_tradfi.status_code == 200

        active_after_delete = await ac.get("/api/v1/universe/active", headers=headers)
        assert active_after_delete.status_code == 200
        active_delete_js = active_after_delete.json()
        assert active_delete_js["symbols"] == ["BTC", "ETH"]
        assert active_delete_js["fallback_to_symbols"] is True

    user_cfg = home / ".b1e55ed" / "config" / "user.yaml"
    assert user_cfg.exists()
    raw = yaml.safe_load(user_cfg.read_text(encoding="utf-8"))
    assert "universe" in raw
    assert "bundles" in raw["universe"]

    db.close()


@pytest.mark.anyio
async def test_universe_pack_catalog_and_pack_based_bundle_creation(temp_dir: Path, test_config, monkeypatch: pytest.MonkeyPatch):
    home = temp_dir / "home"
    monkeypatch.setenv("HOME", str(home))

    cfg = test_config.model_copy(
        update={
            "api": test_config.api.model_copy(update={"auth_token": "secret"}),
            "universe": test_config.universe.model_copy(update={"symbols": ["BTC", "ETH"], "bundles": []}),
        }
    )

    db = Database(temp_dir / "brain-universe-packs.db")
    app = create_app()
    app.state.config = cfg
    app.state.db = db

    headers = {"Authorization": "Bearer secret"}
    async with make_client(app) as ac:
        packs = await ac.get("/api/v1/universe/packs", headers=headers)
        assert packs.status_code == 200
        packs_js = packs.json()
        pack_ids = {item["id"] for item in packs_js["items"]}
        assert {"tradfi-infra", "hl-tradfi-perps", "mixed-market"}.issubset(pack_ids)

        create_from_pack = await ac.post(
            "/api/v1/universe/bundles",
            headers=headers,
            json={
                "pack_id": "hl-tradfi-perps",
                "source": "system",
            },
        )
        assert create_from_pack.status_code == 200, create_from_pack.text
        bundle = create_from_pack.json()
        assert bundle["id"] == "hl-tradfi-perps"
        # hl-tradfi-perps now contains HL equity perps (non-crypto stocks)
        from engine.core.bundle_packs import get_bundle_pack

        expected_symbols = get_bundle_pack("hl-tradfi-perps")["symbols"]
        assert bundle["symbols"] == expected_symbols
        assert "pack:hl-tradfi-perps" in bundle["tags"]
        assert "tradfi" in bundle["tags"]

        active = await ac.get("/api/v1/universe/active", headers=headers)
        assert active.status_code == 200
        active_js = active.json()
        assert active_js["symbols"] == expected_symbols
        assert "tradfi" in active_js["tags"]

    db.close()
