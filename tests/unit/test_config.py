from __future__ import annotations

from pathlib import Path

import pytest

from engine.core.config import Config
from engine.core.exceptions import ConfigError


def test_config_loads_from_yaml_and_preset_chain(tmp_path: Path) -> None:
    # Create minimal config tree.
    cfg_dir = tmp_path / "config"
    presets = cfg_dir / "presets"
    presets.mkdir(parents=True)

    (cfg_dir / "default.yaml").write_text("preset: balanced\n")
    (presets / "balanced.yaml").write_text(
        "weights:\n  curator: 0.25\n  onchain: 0.25\n  tradfi: 0.20\n  social: 0.15\n  technical: 0.10\n  events: 0.05\n"
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
