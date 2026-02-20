from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest


def test_load_identity_returns_none_when_missing(tmp_path: Path) -> None:
    from engine.core.identity_gate import load_identity

    assert load_identity(tmp_path) is None


def test_load_identity_returns_identity(tmp_path: Path) -> None:
    from engine.core.identity_gate import load_identity

    ident_dir = tmp_path / ".b1e55ed"
    ident_dir.mkdir(parents=True, exist_ok=True)
    (ident_dir / "identity.json").write_text(
        json.dumps(
            {
                "address": "0xb1e55ed00000000000000000000000000000000",
                "node_id": "eth:0xb1e55ed00000000000000000000000000000000",
                "forged_at": 123,
                "candidates_evaluated": 456,
                "elapsed_ms": 789,
            }
        ),
        encoding="utf-8",
    )

    ident = load_identity(tmp_path)
    assert ident is not None
    assert ident.address.lower().startswith("0xb1e55ed")
    assert ident.node_id.startswith("eth:")


def test_require_identity_raises(tmp_path: Path) -> None:
    from engine.core.identity_gate import IdentityRequired, require_identity

    with pytest.raises(IdentityRequired):
        _ = require_identity(tmp_path)


def test_cli_gate_blocks_commands_without_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    from engine.cli import main

    monkeypatch.delenv("B1E55ED_DEV_MODE", raising=False)
    monkeypatch.chdir(tmp_path)

    rc = main(["status"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "Identity required" in out


def test_cli_gate_json_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    from engine.cli import main

    monkeypatch.delenv("B1E55ED_DEV_MODE", raising=False)
    monkeypatch.chdir(tmp_path)

    rc = main(["alerts", "--json"])
    out = capsys.readouterr().out.strip()

    assert rc == 1
    msg = json.loads(out)
    assert msg["error"]["code"] == "IDENTITY_REQUIRED"


def test_cli_gate_allows_identity_forge_without_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import engine.cli as cli

    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(cli, "_identity_forge", lambda _ctx, _args: 0)
    assert cli.main(["identity", "forge", "--json"]) == 0


def test_cli_gate_allows_setup_without_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import engine.cli as cli

    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(cli, "_cmd_setup", lambda _ctx, _args: 0)
    assert cli.main(["setup"]) == 0


def _seed_repo_config(dst_root: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    (dst_root / "config").mkdir(parents=True, exist_ok=True)

    shutil.copy2(repo_root / "config" / "default.yaml", dst_root / "config" / "default.yaml")
    shutil.copytree(repo_root / "config" / "presets", dst_root / "config" / "presets")


def test_api_returns_403_without_identity_when_not_dev_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from api.main import create_app

    _seed_repo_config(tmp_path)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("B1E55ED_INSECURE_OK", "1")
    monkeypatch.setenv("B1E55ED_DEV_MODE", "0")

    app = create_app()
    client = TestClient(app)

    res = client.get("/api/v1/signals")
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "IDENTITY_REQUIRED"


def test_api_allows_requests_in_dev_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from api.main import create_app

    _seed_repo_config(tmp_path)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("B1E55ED_INSECURE_OK", "1")
    monkeypatch.setenv("B1E55ED_DEV_MODE", "1")

    app = create_app()
    client = TestClient(app)

    res = client.get("/api/v1/health")
    assert res.status_code == 200
