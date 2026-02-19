from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from engine.cli import build_parser, main
from engine.core.database import Database
from engine.core.events import EventType


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
    assert "event_id" in payload
    assert payload["symbols"] == ["BTC"]
    assert payload["content_len"] == len("BTC looking strong")
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
    assert payload["symbols"] == ["ETH"]
    assert payload["events"][0]["payload"]["rationale"].startswith("ETH")


def test_cli_signal_flags_override_symbols_and_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path)
    monkeypatch.chdir(repo_root)

    rc = main(
        [
            "signal",
            "--json",
            "--symbols",
            "BTC,ETH",
            "--direction",
            "bullish",
            "--conviction",
            "7",
            "--source",
            "operator",
            "Macro shift incoming",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["symbols"] == ["BTC", "ETH"]
    assert payload["content_len"] == len("Macro shift incoming")
    assert payload["events"][0]["payload"]["direction"] == "bullish"
    assert payload["events"][0]["payload"]["conviction"] == 7.0
    assert str(payload["events"][0]["payload"]["source"]).startswith("operator:")


def test_cli_signal_add_accepts_flags_after_subcommand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path)
    monkeypatch.chdir(repo_root)

    fp = repo_root / "note2.txt"
    fp.write_text("ETH looks weak\n", encoding="utf-8")

    rc = main(
        [
            "signal",
            "--json",
            "add",
            "--file",
            str(fp),
            "--direction",
            "bearish",
            "--conviction",
            "3",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["symbols"] == ["ETH"]
    assert payload["events"][0]["payload"]["direction"] == "bearish"
    assert payload["events"][0]["payload"]["conviction"] == 3.0


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


def test_cli_alerts_severity_and_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path)
    monkeypatch.chdir(repo_root)

    db = Database(repo_root / "data" / "brain.db")

    # kill switch -> CRITICAL
    _ = db.append_event(
        event_type=EventType.KILL_SWITCH_V1,
        payload={"level": 2, "previous_level": 0, "reason": "manual:2", "auto": False, "actor": "operator"},
        source="test",
    )

    # producer failure -> WARNING
    db.conn.execute(
        "INSERT OR REPLACE INTO producer_health(name, domain, consecutive_failures, last_error, last_run_at) VALUES(?,?,?,?,?)",
        ("price-ws", "technical", 3, "boom", "2026-02-19T20:00:00+00:00"),
    )
    db.conn.commit()

    rc = main(["alerts", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert {"id", "type", "severity", "message", "meta", "ts"} <= set(payload[0].keys())

    types = {a["type"] for a in payload}
    assert "kill_switch" in types
    assert "producer" in types

    ks = [a for a in payload if a["type"] == "kill_switch"][0]
    assert ks["severity"] == "CRITICAL"

    prod = [a for a in payload if a["type"] == "producer"][0]
    assert prod["severity"] == "WARNING"


def test_cli_alerts_since_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path)
    monkeypatch.chdir(repo_root)

    db = Database(repo_root / "data" / "brain.db")
    db.conn.execute(
        "INSERT OR REPLACE INTO producer_health(name, domain, consecutive_failures, last_error, last_run_at) VALUES(?,?,?,?,?)",
        ("p", "d", 1, "err", "2000-01-01T00:00:00+00:00"),
    )
    db.conn.commit()

    rc = main(["alerts", "--json", "--since", "5"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_cli_alerts_position_near_stop_is_warning_or_critical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path)
    monkeypatch.chdir(repo_root)

    db = Database(repo_root / "data" / "brain.db")

    # mark price
    _ = db.append_event(
        event_type=EventType.SIGNAL_PRICE_WS_V1,
        payload={"symbol": "BTC", "price": 100.0, "venue": "test"},
        source="test",
    )

    # position with stop within 0.5% -> WARNING
    db.conn.execute(
        "INSERT INTO positions(id, platform, asset, direction, entry_price, size_notional, stop_loss, opened_at, status) VALUES(?,?,?,?,?,?,?,?,?)",
        ("pos1", "test", "BTC", "long", 120.0, 1000.0, 99.6, "2026-02-19T20:05:00+00:00", "open"),
    )
    db.conn.commit()

    rc = main(["alerts", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    pos = [a for a in payload if a["type"] == "position"][0]
    assert pos["severity"] in {"WARNING", "CRITICAL"}


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
