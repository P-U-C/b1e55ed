from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

# uv/pytest may run without installing the project; ensure repo root is importable.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.core.config import Config  # noqa: E402


@pytest.fixture()
def temp_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def test_config(temp_dir: Path) -> Config:
    """Config fixture that points data_dir to a temp directory."""

    repo_root = Path(__file__).resolve().parents[1]
    cfg_src = repo_root / "config" / "default.yaml"
    cfg_dst_dir = temp_dir / "config"
    cfg_dst_dir.mkdir(parents=True, exist_ok=True)

    # copy default + presets
    shutil.copy2(cfg_src, cfg_dst_dir / "default.yaml")
    shutil.copytree(repo_root / "config" / "presets", cfg_dst_dir / "presets")

    c = Config.from_yaml(cfg_dst_dir / "default.yaml")
    return c.model_copy(update={"data_dir": temp_dir / "data", "config_dir": cfg_dst_dir})
