"""Tests for the cockpit dashboard — Sprint S6."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.cockpit import router as cockpit_router
from engine.core.database import Database
from engine.core.events import EventType


@pytest.fixture()
def db(tmp_path):
    return Database(db_path=tmp_path / "test.db")


def _make_api_client(db):
    app = FastAPI()
    app.state.db = db
    app.include_router(cockpit_router)
    return TestClient(app)


# ---- API tests ----


def test_cockpit_state_no_data_returns_null_call(db):
    client = _make_api_client(db)
    resp = client.get("/cockpit/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["top_call"] is None
    assert data["producer_signals"] == []
    assert isinstance(data["system"], dict)
    assert data["system"]["kill_switch_level"] == "SAFE"


def test_cockpit_state_with_conviction_returns_top_call(db):
    db.conn.execute(
        """INSERT INTO conviction_scores
           (cycle_id, node_id, symbol, direction, magnitude, timeframe, ts,
            commitment_hash, pcs_score, cts_score, regime, domains_used, confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "cycle-1",
            "node-1",
            "BTC",
            "long",
            7.5,
            "4h",
            datetime.now(tz=UTC).isoformat(),
            "abc123",
            75.0,
            10.0,
            "RISK_ON",
            '["ta","tradfi"]',
            0.68,
        ),
    )
    db.conn.commit()

    client = _make_api_client(db)
    resp = client.get("/cockpit/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["top_call"] is not None
    assert data["top_call"]["symbol"] == "BTC"
    assert data["top_call"]["direction"] == "long"
    assert data["top_call"]["confidence"] == 0.68


def test_cockpit_state_producer_breakdown_sorted_by_confidence(db):
    now = datetime.now(tz=UTC)
    for pid, conf in [("producer-a", 0.8), ("producer-b", 0.5)]:
        payload = {
            "forecast_id": f"f-{pid}",
            "source": f"{pid}@0.0.1",
            "asset": "BTC",
            "horizon": "24h",
            "action": "long",
            "confidence": conf,
            "regime_tag": "unknown",
            "abstention_reason": None,
            "lifecycle_state": "new",
        }
        db.append_event(
            event_type=EventType.FORECAST_V1,
            payload=payload,
            source="test",
            ts=now,
        )

    client = _make_api_client(db)
    resp = client.get("/cockpit/state")
    data = resp.json()
    signals = data["producer_signals"]
    assert len(signals) >= 2
    confs = [s["confidence"] for s in signals]
    assert confs == sorted(confs, reverse=True)


def test_cockpit_state_system_status_includes_kill_switch(db):
    client = _make_api_client(db)
    resp = client.get("/cockpit/state")
    data = resp.json()
    sys = data["system"]
    assert "kill_switch_level" in sys
    assert "consecutive_losses" in sys
    assert "open_risk_pct" in sys
    assert "open_positions" in sys
    assert "last_cycle_ts" in sys


class _Res:
    def __init__(self, data, ok):
        self.data = data
        self.ok = ok


class _DummyApiClient:
    def get_cockpit_state(self):
        return _Res({}, False)

    def get_positions(self):
        return _Res([], False)

    def get_signals(self, domain=None):
        return _Res({"items": [], "total": 0}, False)

    def get_producers_status(self):
        return _Res({"producers": {}}, False)

    def get_regime(self):
        return _Res({"regime": None}, False)

    def get_kill_switch(self):
        return _Res({"kill_switch_level": 0}, False)

    def get_karma_summary(self):
        return _Res({}, False)

    def get_karma_intents(self):
        return _Res({"items": []}, False)

    def get_karma_receipts(self):
        return _Res({"items": []}, False)

    def get_social_sentiment(self):
        return _Res({"items": []}, False)

    def get_social_alerts(self):
        return _Res({"items": []}, False)

    def get_social_narratives(self):
        return _Res({"items": []}, False)

    def get_social_sources(self):
        return _Res({"items": []}, False)

    def get_curator_feed(self):
        return _Res({"items": []}, False)


def _make_dashboard_client():
    os.environ["B1E55ED_DEV_MODE"] = "1"
    from dashboard.app import app

    client = TestClient(app)
    client.app.state.api_client = _DummyApiClient()
    return client


def test_cockpit_page_returns_200():
    client = _make_dashboard_client()
    resp = client.get("/cockpit")
    assert resp.status_code == 200
    assert "cockpit" in resp.text.lower()


def test_cockpit_htmx_refresh_endpoint():
    client = _make_dashboard_client()
    resp = client.get("/partials/cockpit-content")
    assert resp.status_code == 200


def test_producer_breakdown_field_mapping(db):
    """forecast.v1 payload fields map correctly: source→producer_id, asset→domain, action→direction."""
    now = datetime.now(tz=UTC)
    payload = {
        "forecast_id": "f-fieldmap-330",
        "source": "whale-tracker@1.0.0",  # producer_id = "whale-tracker" (strip @version)
        "asset": "ETH",  # domain = "ETH"
        "horizon": "24h",
        "action": "short",  # direction = "short"
        "confidence": 0.77,
        "regime_tag": "bear",
        "abstention_reason": None,
        "lifecycle_state": "new",
    }
    db.append_event(
        event_type=EventType.FORECAST_V1,
        payload=payload,
        source="test",
        ts=now,
    )

    client = _make_api_client(db)
    resp = client.get("/cockpit/state")
    assert resp.status_code == 200
    signals = resp.json()["producer_signals"]
    assert len(signals) >= 1, "Expected at least one signal from forecast.v1 event"

    signal = next((s for s in signals if s["producer_id"] == "whale-tracker"), None)
    assert signal is not None, "producer_id 'whale-tracker' not found — source→producer_id mapping broken"
    assert signal["direction"] == "short", f"Expected direction='short' from action='short', got {signal['direction']}"
    assert signal["domain"] == "ETH", f"Expected domain='ETH' from asset='ETH', got {signal['domain']}"
    assert signal["confidence"] == 0.77


def test_producer_breakdown_does_not_query_old_event_type(db):
    """
    Regression guard: cockpit must NOT fall back to attribution.signal_accepted.v1.

    Seeds ONLY old-style events. If the pre-fix code path is active, signals
    would be non-empty. Correct (post-fix) behaviour: empty list.
    """
    now = datetime.now(tz=UTC)
    for i in range(3):
        db.append_event(
            event_type="attribution.signal_accepted.v1",
            payload={
                "producer_id": f"old-producer-{i}",
                "direction": "long",
                "confidence": 0.8,
            },
            source="test",
            ts=now,
        )

    client = _make_api_client(db)
    resp = client.get("/cockpit/state")
    assert resp.status_code == 200
    signals = resp.json()["producer_signals"]
    assert signals == [], f"Cockpit queried attribution.signal_accepted.v1! Got {len(signals)} signal(s). Only forecast.v1 should populate the breakdown."
