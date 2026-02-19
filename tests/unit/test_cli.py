from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from engine.cli import build_parser, main
from engine.core.database import Database


def _scaffold_repo(tmp_path: Path) -> Path:
    """Create a minimal repo root layout expected by the CLI."""

    repo_root = tmp_path
    src_root = Path(__file__).resolve().parents[2]

    (repo_root / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_root / "config" / "default.yaml", repo_root / "config" / "default.yaml")
    shutil.copytree(src_root / "config" / "presets", repo_root / "config" / "presets")

    (repo_root / "data").mkdir(parents=True, exist_ok=True)
    _ = Database(repo_root / "data" / "brain.db")

    return repo_root


def test_cli_help_includes_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([])
    assert rc == 2
    out = capsys.readouterr().out
    assert "setup" in out
    assert "brain" in out
    assert "signal" in out
    assert "alerts" in out
    assert "positions" in out
    assert "webhooks" in out
    assert "kill-switch" in out
    assert "health" in out
    assert "api" in out
    assert "dashboard" in out
    assert "status" in out


def test_cli_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--version"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out.endswith("(0xb1e55ed)")
    assert out.startswith("b1e55ed v")


def test_cli_unknown_command_errors(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["nope"])  # argparse rejects unknown subcommand

    # main() should surface the same behavior via argparse
    with pytest.raises(SystemExit):
        main(["nope"])


@pytest.mark.parametrize(
    "cmd",
    [
        "setup",
        "brain",
        "signal",
        "alerts",
        "positions",
        "webhooks",
        "kill-switch",
        "health",
        "api",
        "dashboard",
        "status",
    ],
)
def test_cli_parses_all_subcommands(cmd: str) -> None:
    parser = build_parser()
    ns = parser.parse_args([cmd])
    assert ns.command == cmd


def test_cli_signal_creates_curator_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path)
    monkeypatch.chdir(repo_root)

    rc = main(["signal", "--json", "BTC looking strong"])
    assert rc == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["events"][0]["type"] == "signal.curator.v1"
    assert payload["events"][0]["payload"]["rationale"].startswith("BTC")


def test_cli_signal_add_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path)
    monkeypatch.chdir(repo_root)

    fp = repo_root / "note.txt"
    fp.write_text("ETH narrative is improving\n", encoding="utf-8")

    rc = main(["signal", "--json", "add", "--file", str(fp)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["events"][0]["payload"]["rationale"].startswith("ETH")


def test_cli_kill_switch_set_and_show(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path)
    monkeypatch.chdir(repo_root)

    rc = main(["kill-switch", "set", "3", "--json"])
    assert rc == 0
    set_payload = json.loads(capsys.readouterr().out)
    assert set_payload["payload"]["level"] == 3

    rc = main(["kill-switch", "--json"])
    assert rc == 0
    show_payload = json.loads(capsys.readouterr().out)
    assert show_payload["level"] == 3


def test_cli_alerts_and_positions_json_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path)
    monkeypatch.chdir(repo_root)

    rc = main(["alerts", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []

    rc = main(["positions", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_cli_health_returns_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path)
    monkeypatch.chdir(repo_root)

    rc = main(["health", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "ok" in payload
    assert "config" in payload
    assert "db" in payload


def test_cli_webhooks_crud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path)
    monkeypatch.chdir(repo_root)

    rc = main(["webhooks", "add", "http://example/hook", "--events", "signal.*"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ok"
    sub_id = int(out["id"])

    rc = main(["webhooks", "list", "--json"])
    assert rc == 0
    subs = json.loads(capsys.readouterr().out)
    assert any(int(s["id"]) == sub_id for s in subs)

    rc = main(["webhooks", "remove", str(sub_id)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ok"
