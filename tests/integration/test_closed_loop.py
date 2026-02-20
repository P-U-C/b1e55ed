from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from api.main import create_app
from engine.brain.kill_switch import KillSwitch
from engine.brain.orchestrator import BrainOrchestrator
from engine.cli import main
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.policy import TradingPolicy, TradingPolicyEngine
from engine.core.webhooks import list_webhook_subscriptions
from engine.execution.oms import OMS, default_sizer_from_config
from engine.execution.paper import PaperBroker
from engine.execution.preflight import Preflight
from engine.security.identity import generate_node_identity
from tests.unit._api_test_client import make_client


def _init_minimal_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "config" / "presets").mkdir(parents=True)
    (tmp_path / "data").mkdir(parents=True)

    preset_yaml = (
        "weights:\n"
        "  curator: 0.25\n"
        "  onchain: 0.25\n"
        "  tradfi: 0.20\n"
        "  social: 0.15\n"
        "  technical: 0.10\n"
        "  events: 0.05\n"
        "universe:\n"
        "  symbols: [BTC]\n"
        "execution:\n"
        "  mode: paper\n"
    )

    for name in ["conservative", "balanced", "degen"]:
        (tmp_path / "config" / "presets" / f"{name}.yaml").write_text(preset_yaml, encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    # Ensure HOME is isolated for identity/keystore.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("B1E55ED_DEV_MODE", "1")
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test")

    return tmp_path


def _append_minimal_signals(db: Database, *, symbol: str = "BTC") -> None:
    now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    db.append_event(
        event_type=EventType.SIGNAL_TA_V1,
        payload={"symbol": symbol, "rsi_14": 30.0, "trend_strength": 0.8},
        source="test",
        ts=now,
    )
    db.append_event(
        event_type=EventType.SIGNAL_ONCHAIN_V1,
        payload={"symbol": symbol, "whale_netflow": 80.0, "exchange_flow": -20.0},
        source="test",
        ts=now,
    )
    db.append_event(
        event_type=EventType.SIGNAL_TRADFI_V1,
        payload={"symbol": symbol, "funding_annualized": 10.0, "basis_annualized": 5.0},
        source="test",
        ts=now,
    )


def test_fresh_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _init_minimal_repo(tmp_path, monkeypatch)

    monkeypatch.setenv("B1E55ED_NONINTERACTIVE", "1")
    monkeypatch.setenv("B1E55ED_PRESET", "balanced")

    rc = main(["setup", "--non-interactive"])
    assert rc == 0

    assert (repo_root / "config" / "user.yaml").exists()
    assert (repo_root / "data" / "brain.db").exists()

    cfg = Config.from_yaml(repo_root / "config" / "user.yaml")
    db = Database(repo_root / "data" / "brain.db")

    _append_minimal_signals(db)

    ident = generate_node_identity()
    orch = BrainOrchestrator(cfg, db, ident)
    out = orch.run_cycle(["BTC"])

    assert "BTC" in out.convictions
    db.close()


def test_signal_to_brain_to_alert(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _init_minimal_repo(tmp_path, monkeypatch)

    monkeypatch.setenv("B1E55ED_NONINTERACTIVE", "1")
    monkeypatch.setenv("B1E55ED_PRESET", "balanced")
    assert main(["setup", "--non-interactive"]) == 0

    # 1) Operator signal
    rc_sig = main(
        [
            "signal",
            "BTC looks strong",
            "--symbols",
            "BTC",
            "--source",
            "operator",
            "--direction",
            "bullish",
            "--conviction",
            "8",
            "--json",
        ]
    )
    assert rc_sig == 0

    cfg = Config.from_yaml(repo_root / "config" / "user.yaml")
    db = Database(repo_root / "data" / "brain.db")

    # 2) Brain cycle
    _append_minimal_signals(db)
    ident = generate_node_identity()
    orch = BrainOrchestrator(cfg, db, ident)
    _ = orch.run_cycle(["BTC"])

    # 3) Execution creates a position with a stop; alerts should surface it when mark breaches.
    # BrainOrchestrator returns intents as JSON dicts; for deterministic execution wiring we force a TradeIntent.
    from engine.core.types import TradeIntent

    intent = TradeIntent(
        symbol="BTC",
        direction="long",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=80.0,
        regime="BULL",
        rationale="forced intent for closed loop",
        stop_loss_pct=0.05,
        take_profit_pct=0.10,
    )

    ks = KillSwitch(config=cfg, db=db)
    preflight = Preflight(policy=TradingPolicyEngine(policy=TradingPolicy()), kill_switch=ks)
    oms = OMS(
        config=cfg,
        db=db,
        preflight=preflight,
        sizer=default_sizer_from_config(cfg),
        paper_broker=PaperBroker(db=db),
    )

    res = oms.submit(intent=intent, mid_price=100.0, equity_usd=10_000.0)
    assert res.status == "filled"

    # Emit a mark price below the stop to trigger alert severity.
    db.append_event(
        event_type=EventType.SIGNAL_PRICE_WS_V1,
        payload={"symbol": "BTC", "price": 90.0, "source": "test"},
        source="test",
        ts=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
    )

    alerts_json = _capture_stdout(lambda: main(["alerts", "--json"]))
    js = json.loads(alerts_json)

    assert any(a.get("type") == "position" for a in js)

    db.close()


@pytest.mark.anyio
async def test_producer_registration_lifecycle(temp_dir: Path, test_config: Config) -> None:
    app = create_app()
    app.state.config = test_config
    app.state.db = Database(temp_dir / "brain.db")

    async with make_client(app) as ac:
        reg = {
            "name": "it-producer",
            "domain": "technical",
            "endpoint": "https://example.com/signals",
            "schedule": "*/5 * * * *",
        }

        r1 = await ac.post("/api/v1/producers/register", json=reg)
        assert r1.status_code == 200

        r2 = await ac.get("/api/v1/producers/")
        assert r2.status_code == 200
        assert any(p["name"] == "it-producer" for p in r2.json()["producers"])

        # Brain should run with the same DB even if external producers are registered.
        _append_minimal_signals(app.state.db)
        ident = generate_node_identity()
        out = BrainOrchestrator(test_config, app.state.db, ident).run_cycle(["BTC"])
        assert "BTC" in out.convictions

        r3 = await ac.delete("/api/v1/producers/it-producer")
        assert r3.status_code == 200

    app.state.db.close()


def test_multi_signal_no_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _init_minimal_repo(tmp_path, monkeypatch)

    monkeypatch.setenv("B1E55ED_NONINTERACTIVE", "1")
    monkeypatch.setenv("B1E55ED_PRESET", "balanced")
    assert main(["setup", "--non-interactive"]) == 0

    assert main(["signal", "BTC A", "--symbols", "BTC", "--source", "agent-a", "--direction", "bullish", "--conviction", "7"]) == 0
    assert main(["signal", "BTC B", "--symbols", "BTC", "--source", "agent-b", "--direction", "bearish", "--conviction", "6"]) == 0

    db = Database(repo_root / "data" / "brain.db")
    rows = db.get_events(event_type=EventType.SIGNAL_CURATOR_V1, limit=50)

    sources = {str(e.payload.get("source")) for e in rows}
    assert any(s.startswith("agent-a") for s in sources)
    assert any(s.startswith("agent-b") for s in sources)

    cfg = Config.from_yaml(repo_root / "config" / "user.yaml")
    _append_minimal_signals(db)
    out = BrainOrchestrator(cfg, db, generate_node_identity()).run_cycle(["BTC"])
    assert "BTC" in out.convictions

    db.close()


def test_graceful_degradation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _init_minimal_repo(tmp_path, monkeypatch)

    # No API server started. Brain should still run.
    monkeypatch.setenv("B1E55ED_NONINTERACTIVE", "1")
    monkeypatch.setenv("B1E55ED_PRESET", "balanced")
    assert main(["setup", "--non-interactive"]) == 0

    cfg = Config.from_yaml(repo_root / "config" / "user.yaml")
    db = Database(repo_root / "data" / "brain.db")
    _append_minimal_signals(db)

    out = BrainOrchestrator(cfg, db, generate_node_identity()).run_cycle(["BTC"])
    assert "BTC" in out.convictions
    db.close()


def test_cold_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _init_minimal_repo(tmp_path, monkeypatch)

    # Explicitly avoid any configured API keys.
    for k in list(os.environ.keys()):
        if k.startswith("B1E55ED_") and "KEY" in k:
            monkeypatch.delenv(k, raising=False)

    monkeypatch.setenv("B1E55ED_NONINTERACTIVE", "1")
    monkeypatch.setenv("B1E55ED_PRESET", "balanced")

    assert main(["setup", "--non-interactive"]) == 0

    cfg = Config.from_yaml(repo_root / "config" / "user.yaml")
    db = Database(repo_root / "data" / "brain.db")
    _append_minimal_signals(db)

    out = BrainOrchestrator(cfg, db, generate_node_identity()).run_cycle(["BTC"])
    assert "BTC" in out.convictions
    db.close()


def test_webhook_delivery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _init_minimal_repo(tmp_path, monkeypatch)

    monkeypatch.setenv("B1E55ED_NONINTERACTIVE", "1")
    monkeypatch.setenv("B1E55ED_PRESET", "balanced")
    assert main(["setup", "--non-interactive"]) == 0

    # Register webhook via CLI.
    assert main(["webhooks", "add", "http://example/hook", "--events", "signal.price_alert.*"]) == 0

    db = Database(repo_root / "data" / "brain.db")
    subs = list_webhook_subscriptions(db)
    assert subs

    sent: list[dict[str, object]] = []

    def fake_post_json(url: str, payload: dict[str, object], *, timeout_s: float) -> None:
        sent.append({"url": url, "payload": payload, "timeout_s": timeout_s})

    monkeypatch.setattr("engine.core.webhooks._post_json", fake_post_json)

    db.append_event(
        event_type=EventType.SIGNAL_PRICE_ALERT_V1,
        payload={"symbol": "BTC", "price": 123.45, "rule": "test"},
        ts=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    )

    assert len(sent) == 1
    assert sent[0]["url"] == "http://example/hook"
    assert sent[0]["payload"]["event"]["type"] == str(EventType.SIGNAL_PRICE_ALERT_V1)

    db.close()


def _capture_stdout(fn) -> str:
    import io
    import sys

    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        fn()
    finally:
        sys.stdout = old
    return buf.getvalue().strip()
