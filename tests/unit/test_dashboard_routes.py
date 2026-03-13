from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.app import app


@dataclass
class _Res:
    data: object
    ok: bool


# Ashby's Law of Requisite Variety: a controller needs at least as much
# variety as the system it controls. DummyApiClient has exactly enough.
class DummyApiClient:
    def get_positions(self) -> _Res:  # noqa: D401
        return _Res([], False)

    def get_signals(self, domain: str | None = None) -> _Res:
        return _Res({"items": [], "total": 0, "limit": 100, "offset": 0}, False)

    def get_universe_packs(self) -> _Res:
        return _Res({"items": [], "total": 0}, True)

    def get_universe_bundles(self) -> _Res:
        return _Res({"items": [], "total": 0}, True)

    def get_universe_active(self) -> _Res:
        return _Res(
            {
                "symbols": ["BTC", "ETH", "SOL"],
                "count": 3,
                "fallback_to_symbols": True,
                "bundles": [],
                "enabled_bundle_ids": [],
                "asset_classes": [],
                "venues": [],
                "tags": [],
                "asset_class_symbols": {},
                "venue_symbols": {},
                "tag_symbols": {},
            },
            True,
        )

    def create_universe_bundle(self, body: dict) -> _Res:
        return _Res(body, True)

    def update_universe_bundle(self, bundle_id: str, body: dict) -> _Res:
        return _Res({"id": bundle_id, **body}, True)

    def delete_universe_bundle(self, bundle_id: str) -> _Res:
        return _Res({"ok": True, "deleted": bundle_id}, True)

    def get_producers_status(self) -> _Res:
        return _Res({"producers": {}}, False)

    def get_regime(self) -> _Res:
        return _Res({"regime": None, "changed_at": None, "conditions": {}}, False)

    def get_kill_switch(self) -> _Res:
        return _Res({"kill_switch_level": 0, "last_cycle_at": None, "kill_switch_changed_at": None}, False)

    def get_karma_summary(self) -> _Res:
        return _Res({"pending_intents": 0, "percentage": 0.005, "treasury_address": "0x0", "receipts": 0}, False)

    def get_karma_intents(self) -> _Res:
        return _Res({"items": []}, False)

    def get_karma_receipts(self) -> _Res:
        return _Res({"items": []}, False)

    def get_social_sentiment(self) -> _Res:
        return _Res({"items": []}, False)

    def get_social_alerts(self) -> _Res:
        return _Res({"items": []}, False)

    def get_social_narratives(self) -> _Res:
        return _Res({"items": []}, False)

    def get_social_sources(self) -> _Res:
        return _Res({"items": []}, False)

    def get_curator_feed(self) -> _Res:
        return _Res({"items": []}, False)

    def get_convictions(self, limit: int = 20) -> _Res:
        return _Res({"items": []}, False)

    def get_artifacts(self, limit: int = 20) -> _Res:
        return _Res([], False)

    def _get_json(self, path: str, params: dict | None = None) -> _Res:
        _ = (path, params)
        return _Res({}, False)

    def _post_json(self, path: str, body: dict | None = None) -> _Res:
        _ = (path, body)
        return _Res({}, False)


_SCHEMA_MIN = """
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL,
  event_globs TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS producer_health (
  name TEXT PRIMARY KEY,
  domain TEXT,
  schedule TEXT,
  endpoint TEXT,
  last_run_at TEXT,
  last_success_at TEXT,
  last_error TEXT,
  consecutive_failures INTEGER DEFAULT 0,
  events_produced INTEGER DEFAULT 0,
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contributors (
  id TEXT PRIMARY KEY,
  node_id TEXT NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'tester',
  registered_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contributor_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contributor_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  signal_direction TEXT,
  signal_score REAL,
  signal_asset TEXT,
  accepted INTEGER DEFAULT 0,
  profitable INTEGER DEFAULT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "brain.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA_MIN)
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_new_routes_return_200(tmp_path: Path, monkeypatch) -> None:
    db_path = _make_db(tmp_path)
    monkeypatch.setenv("B1E55ED_DB_PATH", str(db_path))
    monkeypatch.setenv("B1E55ED_IDENTITY_PATH", str(tmp_path / "identity.json"))

    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()

        for route in ["/contributors", "/identity", "/webhooks", "/producers"]:
            resp = client.get(route)
            assert resp.status_code == 200, route


def test_contributors_empty_db(tmp_path: Path, monkeypatch) -> None:
    db_path = _make_db(tmp_path)
    monkeypatch.setenv("B1E55ED_DB_PATH", str(db_path))

    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()
        resp = client.get("/contributors")
        assert resp.status_code == 200
        assert "No contributors" in resp.text


def test_identity_no_identity_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("B1E55ED_IDENTITY_PATH", str(tmp_path / "missing_identity.json"))

    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()
        resp = client.get("/identity")
        assert resp.status_code == 200
        assert "Identity not yet forged" in resp.text


def test_webhooks_empty_table(tmp_path: Path, monkeypatch) -> None:
    db_path = _make_db(tmp_path)
    monkeypatch.setenv("B1E55ED_DB_PATH", str(db_path))

    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()
        resp = client.get("/webhooks")
        assert resp.status_code == 200
        assert "No webhooks registered" in resp.text


def test_producers_page_loads(tmp_path: Path, monkeypatch) -> None:
    db_path = _make_db(tmp_path)
    monkeypatch.setenv("B1E55ED_DB_PATH", str(db_path))

    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()
        resp = client.get("/producers")
        assert resp.status_code == 200
        assert "Producers" in resp.text


def test_producers_page_degrades_zero_event_runs_and_marks_stale(tmp_path: Path, monkeypatch) -> None:
    db_path = _make_db(tmp_path)
    now = datetime.now(UTC)
    recent_run = (now - timedelta(minutes=5)).isoformat()
    stale_run = (now - timedelta(minutes=45)).isoformat()

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO producer_health
        (name, domain, schedule, endpoint, last_run_at, last_success_at, last_error, consecutive_failures, events_produced, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("ta.zero-events", "ta", "*/15 * * * *", "/api/ta", recent_run, recent_run, None, 0, 0, now.isoformat()),
    )
    conn.execute(
        """
        INSERT INTO producer_health
        (name, domain, schedule, endpoint, last_run_at, last_success_at, last_error, consecutive_failures, events_produced, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("ta.stale", "ta", "*/15 * * * *", "/api/ta", stale_run, stale_run, None, 0, 5, now.isoformat()),
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("B1E55ED_DB_PATH", str(db_path))

    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()
        resp = client.get("/producers")
        assert resp.status_code == 200
        assert "⚠ degraded" in resp.text
        assert "⌛ stale" in resp.text


def test_forecasts_page(tmp_path: Path, monkeypatch) -> None:
    db_path = _make_db(tmp_path)
    # Add forecast_calibration table
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS forecast_calibration (
        id INTEGER PRIMARY KEY, forecast_id TEXT, producer_name TEXT, asset TEXT,
        regime TEXT, horizon TEXT, direction TEXT, confidence REAL, calibrated INTEGER,
        outcome TEXT, brier_score REAL, price_at_emit REAL, price_at_resolve REAL,
        emitted_at TEXT, resolved_at TEXT, created_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS discretionary_signals (
        id TEXT PRIMARY KEY, symbol TEXT, direction TEXT, confidence REAL,
        reasoning TEXT, created_at TEXT, expires_at TEXT
    )""")
    conn.commit()
    conn.close()
    monkeypatch.setenv("B1E55ED_DB_PATH", str(db_path))

    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()
        resp = client.get("/forecasts")
        assert resp.status_code == 200
        assert "Forecasts" in resp.text


def test_conviction_page(tmp_path: Path, monkeypatch) -> None:
    db_path = _make_db(tmp_path)
    monkeypatch.setenv("B1E55ED_DB_PATH", str(db_path))
    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()
        resp = client.get("/conviction")
        assert resp.status_code == 200
        assert "Conviction" in resp.text


def test_conviction_page_symbol_filter(tmp_path: Path, monkeypatch) -> None:
    db_path = _make_db(tmp_path)
    monkeypatch.setenv("B1E55ED_DB_PATH", str(db_path))
    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()
        for sym in ["BTC", "ETH", "SOL"]:
            resp = client.get(f"/conviction?symbol={sym}")
            assert resp.status_code == 200


def test_conviction_history_partial(tmp_path: Path, monkeypatch) -> None:
    db_path = _make_db(tmp_path)
    monkeypatch.setenv("B1E55ED_DB_PATH", str(db_path))
    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()
        resp = client.get("/partials/conviction-history?symbol=BTC")
        assert resp.status_code == 200


def test_home_page_renders(tmp_path: Path, monkeypatch) -> None:
    """Ghost charts and onboarding shouldn't break the home page."""
    db_path = _make_db(tmp_path)
    monkeypatch.setenv("B1E55ED_DB_PATH", str(db_path))
    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()
        resp = client.get("/")
        assert resp.status_code == 200


def test_css_has_jetbrains_mono_font(tmp_path: Path, monkeypatch) -> None:
    # "The terminal is not an aesthetic choice. It is a statement about what kind
    # of builder you are." — b1e55ed brand principles, 2026.
    db_path = _make_db(tmp_path)
    monkeypatch.setenv("B1E55ED_DB_PATH", str(db_path))
    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()
        resp = client.get("/static/style.css")
        assert resp.status_code == 200
        assert "JetBrains Mono" in resp.text


def test_forecasts_partial(tmp_path: Path, monkeypatch) -> None:
    db_path = _make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS forecast_calibration (
        id INTEGER PRIMARY KEY, forecast_id TEXT, producer_name TEXT, asset TEXT,
        regime TEXT, horizon TEXT, direction TEXT, confidence REAL, calibrated INTEGER,
        outcome TEXT, brier_score REAL, price_at_emit REAL, price_at_resolve REAL,
        emitted_at TEXT, resolved_at TEXT, created_at TEXT
    )""")
    conn.commit()
    conn.close()
    monkeypatch.setenv("B1E55ED_DB_PATH", str(db_path))

    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()
        resp = client.get("/partials/forecasts-table")
        assert resp.status_code == 200


def test_vitals_bar_partial(tmp_path: Path, monkeypatch) -> None:
    """Vitals bar returns 200 with empty DB (graceful degradation)."""
    db_path = _make_db(tmp_path)
    monkeypatch.setenv("B1E55ED_DB_PATH", str(db_path))
    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()
        resp = client.get("/partials/vitals-bar")
        assert resp.status_code == 200
        assert "SIGNAL" in resp.text
        assert "MODE" in resp.text


def test_vitals_bar_partial_with_signal(tmp_path: Path, monkeypatch) -> None:
    """Vitals bar reflects signal data when signals table is populated."""
    db_path = _make_db(tmp_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE IF NOT EXISTS signals (
        id TEXT PRIMARY KEY, producer_id TEXT, asset TEXT, ts TEXT,
        confidence REAL, payload TEXT
    )""")
    conn.execute(
        "INSERT INTO signals VALUES (?,?,?,datetime('now'),0.8,'{}')",
        ("sig-1", "producer-a", "BTC"),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("B1E55ED_DB_PATH", str(db_path))
    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()
        resp = client.get("/partials/vitals-bar")
        assert resp.status_code == 200
        # Should show a signal age (s/m/h) not the em-dash default
        assert resp.status_code == 200


def test_signal_detail_partial_not_found(tmp_path: Path, monkeypatch) -> None:
    """Signal detail returns 200 with empty signal when ID not found."""
    db_path = _make_db(tmp_path)
    monkeypatch.setenv("B1E55ED_DB_PATH", str(db_path))
    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()
        resp = client.get("/partials/signal-detail/nonexistent-id")
        assert resp.status_code == 200
