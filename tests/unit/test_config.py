from __future__ import annotations

from pathlib import Path

import pytest

from engine.core.config import Config, DomainWeights, UniverseBundle
from engine.core.exceptions import ConfigError


def test_domain_weights_must_sum_to_one() -> None:
    w = DomainWeights(curator=0.25, onchain=0.20, tradfi=0.20, social=0.15, technical=0.10, events=0.10)
    assert w.curator == 0.25


def test_config_loads_from_yaml_and_preset_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure env doesn't interfere
    monkeypatch.chdir(tmp_path)

    cfg_dir = tmp_path / "config"
    presets = cfg_dir / "presets"
    presets.mkdir(parents=True)

    (cfg_dir / "default.yaml").write_text("preset: balanced\n")
    preset_yaml = """\
weights:
  curator: 0.25
  onchain: 0.20
  tradfi: 0.20
  social: 0.15
  technical: 0.10
  events: 0.10
"""
    (presets / "balanced.yaml").write_text(preset_yaml)

    cfg = Config.from_yaml(cfg_dir / "default.yaml")
    assert cfg.preset == "balanced"
    assert cfg.weights.curator == 0.25


def test_config_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("B1E55ED_EXECUTION__MODE", "live")
    cfg = Config()  # BaseSettings reads env
    assert cfg.execution.mode == "live"


def test_config_from_yaml_raises_if_missing(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        Config.from_yaml(tmp_path / "missing.yaml")


def test_execution_bundle_policy_defaults() -> None:
    cfg = Config()
    assert cfg.execution.allowed_bundle_asset_classes == ["crypto"]
    assert "global" in cfg.execution.allowed_bundle_venues


def test_universe_active_symbols_prefers_enabled_bundles() -> None:
    cfg = Config(
        universe={
            "symbols": ["BTC", "ETH"],
            "max_size": 10,
            "bundles": [
                {
                    "id": "crypto-core",
                    "name": "Crypto Core",
                    "symbols": ["SOL", "BTC"],
                    "asset_class": "crypto",
                    "venue": "global",
                    "enabled": True,
                    "source": "user",
                },
                {
                    "id": "disabled",
                    "name": "Disabled",
                    "symbols": ["DOGE"],
                    "asset_class": "crypto",
                    "venue": "global",
                    "enabled": False,
                    "source": "user",
                },
            ],
        }
    )

    assert cfg.universe.active_symbols() == ["SOL", "BTC"]


def test_universe_execution_metadata_for_symbol() -> None:
    universe = Config().universe.model_copy(
        update={
            "bundles": [
                UniverseBundle(
                    id="crypto-core",
                    name="Crypto Core",
                    symbols=["BTC"],
                    tags=["core", "paper-only"],
                    asset_class="crypto",
                    venue="global",
                    execution_mode_hint="paper_only",
                    enabled=True,
                    source="user",
                ),
                UniverseBundle(
                    id="alt",
                    name="Alt",
                    symbols=["BTC", "ETH"],
                    tags=["growth"],
                    asset_class="crypto",
                    venue="binance",
                    enabled=True,
                    source="user",
                ),
            ]
        }
    )

    meta = universe.execution_metadata_for_symbol("btc")

    assert meta["bundle_ids"] == ["crypto-core", "alt"]
    assert meta["asset_classes"] == ["crypto"]
    assert meta["venues"] == ["binance", "global"]
    assert meta["tags"] == ["core", "growth", "paper-only"]
    assert meta["execution_mode_hints"] == ["paper_only"]
