from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from engine.cli import build_parser, main
from engine.core.database import Database
from engine.core.events import EventType


def _scaffold_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch | None = None) -> Path:
    """Create a minimal repo root layout expected by the CLI.

    When *monkeypatch* is supplied the function also isolates HOME so that
    ``_resolve_db_path`` uses ``tmp_path/home/.b1e55ed/data/brain.db``
    instead of the real ``~/.b1e55ed/data/brain.db``.
    """

    repo_root = tmp_path
    src_root = Path(__file__).resolve().parents[2]

    (repo_root / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_root / "config" / "default.yaml", repo_root / "config" / "default.yaml")
    shutil.copytree(src_root / "config" / "presets", repo_root / "config" / "presets")

    # Provide explicit symbols so signal extraction has a stable universe.
    # (default.yaml now derives symbols from enabled bundles; tests need a fixed list)
    (repo_root / "config" / "user.yaml").write_text("universe:\n  symbols: [BTC, ETH, SOL, SUI, HYPE]\n")

    # Marker so _repo_root_from_cwd detects this as a dev checkout
    (repo_root / "pyproject.toml").write_text("[project]\nname='b1e55ed'\n")

    # Isolate HOME so _resolve_db_path points to the temp dir.
    home_dir = tmp_path / "home"
    if monkeypatch is not None:
        monkeypatch.setenv("HOME", str(home_dir))

    # Create brain.db at the new default path (~/.b1e55ed/data/).
    data_dir = home_dir / ".b1e55ed" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _ = Database(data_dir / "brain.db")

    # Create fake forged identity so the identity gate doesn't block CLI tests.
    identity_dir = home_dir / ".b1e55ed"
    identity_dir.mkdir(parents=True, exist_ok=True)
    (identity_dir / "identity.json").write_text(
        json.dumps(
            {
                "address": "0xb1e55ed0000000000000000000000000deadbeef",
                "node_id": "eth:0xb1e55ed0000000000000000000000000deadbeef",
                "forged_at": 1700000000,
                "candidates_evaluated": 1,
                "elapsed_ms": 1,
            }
        )
    )

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
    assert "pause" in out
    assert "resume" in out
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
        "pause",
        "resume",
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
    repo_root = _scaffold_repo(tmp_path, monkeypatch)
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
    repo_root = _scaffold_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo_root)

    fp = repo_root / "note.txt"
    fp.write_text("ETH narrative is improving\n", encoding="utf-8")

    rc = main(["signal", "--json", "add", "--file", str(fp)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["symbols"] == ["ETH"]
    assert payload["events"][0]["payload"]["rationale"].startswith("ETH")


def test_cli_signal_flags_override_symbols_and_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path, monkeypatch)
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
    repo_root = _scaffold_repo(tmp_path, monkeypatch)
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
    repo_root = _scaffold_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo_root)

    rc = main(["kill-switch", "set", "3", "--json"])
    assert rc == 0
    set_payload = json.loads(capsys.readouterr().out)
    assert set_payload["payload"]["level"] == 3

    rc = main(["kill-switch", "--json"])
    assert rc == 0
    show_payload = json.loads(capsys.readouterr().out)
    assert show_payload["level"] == 3


def test_cli_pause_and_resume_emit_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo_root)

    rc = main(["pause", "--reason", "reviewing signals", "--json"])
    assert rc == 0
    pause_payload = json.loads(capsys.readouterr().out)
    assert pause_payload["payload"]["reason"] == "reviewing signals"

    rc = main(["resume", "--json"])
    assert rc == 0
    resume_payload = json.loads(capsys.readouterr().out)
    assert resume_payload["payload"]["consumed_by"] == "operator"

    db = Database(tmp_path / "home" / ".b1e55ed" / "data" / "brain.db")
    pause_events = db.get_events(event_type=EventType.PAUSE_V1, limit=1)
    consumed_events = db.get_events(event_type=EventType.PAUSE_CONSUMED_V1, limit=1)

    assert pause_events
    assert consumed_events


def test_cli_alerts_and_positions_json_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo_root)

    rc = main(["alerts", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []

    rc = main(["positions", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_cli_alerts_severity_and_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo_root)

    db = Database(tmp_path / "home" / ".b1e55ed" / "data" / "brain.db")

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
    repo_root = _scaffold_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo_root)

    db = Database(tmp_path / "home" / ".b1e55ed" / "data" / "brain.db")
    db.conn.execute(
        "INSERT OR REPLACE INTO producer_health(name, domain, consecutive_failures, last_error, last_run_at) VALUES(?,?,?,?,?)",
        ("p", "d", 1, "err", "2000-01-01T00:00:00+00:00"),
    )
    db.conn.commit()

    rc = main(["alerts", "--json", "--since", "5"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_cli_alerts_position_near_stop_is_warning_or_critical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo_root)

    db = Database(tmp_path / "home" / ".b1e55ed" / "data" / "brain.db")

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
    repo_root = _scaffold_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo_root)

    rc = main(["health", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "ok" in payload
    assert "config" in payload
    assert "db" in payload


def test_cli_webhooks_crud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = _scaffold_repo(tmp_path, monkeypatch)
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


class TestModuleExecution:
    def test_python_m_engine_cli_importable(self) -> None:
        """python -m engine.cli must work — requires engine/cli/__main__.py."""
        import importlib

        # __main__.py must exist and be importable
        spec = importlib.util.find_spec("engine.cli.__main__")
        assert spec is not None, "engine/cli/__main__.py missing — 'python -m engine.cli' will fail"

    def test_python_m_engine_cli_runs(self) -> None:
        """Running engine.cli as a module must invoke main()."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "engine.cli", "--help"],
            capture_output=True,
            text=True,
        )
        # --help exits with 0 and prints usage
        assert result.returncode == 0
        assert "usage" in result.stdout.lower()


# ---------------------------------------------------------------------------
# _repo_root_from_cwd tests
# ---------------------------------------------------------------------------


class TestRepoRootFromCwd:
    """Verify _repo_root_from_cwd resolves correctly for dev vs production."""

    def test_dev_checkout_returns_repo_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When pyproject.toml exists in cwd, return cwd (dev checkout)."""
        from engine.cli.main import _repo_root_from_cwd

        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
        monkeypatch.chdir(tmp_path)
        assert _repo_root_from_cwd() == tmp_path

    def test_dev_checkout_parent_pyproject(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When pyproject.toml exists in a parent, return that parent."""
        from engine.cli.main import _repo_root_from_cwd

        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
        sub = tmp_path / "engine" / "cli"
        sub.mkdir(parents=True)
        monkeypatch.chdir(sub)
        assert _repo_root_from_cwd() == tmp_path

    def test_production_returns_dot_b1e55ed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No pyproject.toml anywhere → return ~/.b1e55ed (production)."""
        from engine.cli.main import _repo_root_from_cwd

        # Create a clean dir with no pyproject.toml
        prod_dir = tmp_path / "prod_home"
        prod_dir.mkdir()
        monkeypatch.chdir(prod_dir)
        result = _repo_root_from_cwd()
        assert result == Path.home() / ".b1e55ed"
