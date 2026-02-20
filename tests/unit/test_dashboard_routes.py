from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.app import app


@dataclass
class _Res:
    data: object
    ok: bool


class DummyApiClient:
    def get_positions(self) -> _Res:  # noqa: D401
        return _Res([], False)

    def get_signals(self, domain: str | None = None) -> _Res:
        return _Res({"items": [], "total": 0, "limit": 100, "offset": 0}, False)

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

    def _get_json(self, path: str, params: dict | None = None) -> _Res:
        _ = (path, params)
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
        assert "Registered Producers" in resp.text
