from __future__ import annotations

import os
from pathlib import Path

from engine.cli import main


def test_setup_non_interactive_creates_config_identity_and_db(tmp_path: Path, monkeypatch) -> None:
    # Create a minimal repo skeleton in tmp_path
    (tmp_path / "config" / "presets").mkdir(parents=True)
    (tmp_path / "data").mkdir(parents=True)

    preset_yaml = "weights:\n  curator: 0.25\n  onchain: 0.25\n  tradfi: 0.20\n  social: 0.15\n  technical: 0.10\n  events: 0.05\n"

    # Minimal presets (content doesn't matter for setup beyond existence)
    for name in ["conservative", "balanced", "degen"]:
        (tmp_path / "config" / "presets" / f"{name}.yaml").write_text(
            preset_yaml,
            encoding="utf-8",
        )

    monkeypatch.chdir(tmp_path)

    # Ensure HOME is isolated
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("B1E55ED_NONINTERACTIVE", "1")
    monkeypatch.setenv("B1E55ED_PRESET", "balanced")

    rc = main(["setup", "--non-interactive"])
    assert rc == 0

    assert (tmp_path / "config" / "user.yaml").exists()
    assert (Path(os.environ["HOME"]) / ".b1e55ed" / "identity.key").exists()
    assert (tmp_path / "data" / "brain.db").exists()
