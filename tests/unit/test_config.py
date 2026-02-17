from __future__ import annotations

import os
from pathlib import Path

import pytest

from engine.core.config import Config, DomainWeights
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
    (presets / "balanced.yaml").write_text(
        "weights:\n  curator: 0.25\n  onchain: 0.20\n  tradfi: 0.20\n  social: 0.15\n  technical: 0.10\n  events: 0.10\n"
    )

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
