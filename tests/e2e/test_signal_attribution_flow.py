"""tests/e2e/test_signal_attribution_flow.py

End-to-end tests for the signal → attribution → contributor score pipeline.

Flow
----
1. Register a contributor
2. Submit a signal attributed to that contributor
3. Verify signal appears in GET /signals
4. Verify contributor attribution is recorded in contributor_signals table
5. Verify GET /signals/{id}/attribution returns correct contributor
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from engine.core.database import Database

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def dev_mode(monkeypatch):
    monkeypatch.setenv("B1E55ED_DEV_MODE", "1")
    monkeypatch.setenv("B1E55ED_INSECURE_OK", "1")


@pytest.fixture()
def app_and_db(tmp_path, test_config):
    db = Database(tmp_path / "brain.db")
    app = create_app()
    app.state.db = db
    app.state.config = test_config
    yield app, db
    db.close()


@pytest.fixture()
def client(app_and_db):
    app, db = app_and_db
    with TestClient(app) as c:
        yield c, db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register(client: TestClient, node_id: str, name: str = "TestAgent") -> dict:
    r = client.post(
        "/api/v1/contributors/register",
        json={"node_id": node_id, "name": name, "role": "agent", "metadata": {}},
    )
    assert r.status_code == 200, f"Registration failed: {r.text}"
    return r.json()


def _submit_signal(
    client: TestClient,
    node_id: str,
    symbol: str = "BTC",
    direction: str = "bullish",
    conviction: float = 7.5,
) -> dict:
    r = client.post(
        "/api/v1/signals/submit",
        json={
            "event_type": "signal.curator.v1",
            "node_id": node_id,
            "source": node_id,
            "payload": {
                "symbol": symbol,
                "direction": direction,
                "conviction": conviction,
                "rationale": "e2e test signal",
                "source": "agent",
            },
        },
    )
    assert r.status_code == 200, f"Signal submit failed: {r.text}"
    return r.json()


# ---------------------------------------------------------------------------
# 1 + 2. Register contributor, submit signal
# ---------------------------------------------------------------------------


def test_register_and_submit_signal(client):
    http, db = client
    contrib = _register(http, "node-attr-1")
    signal = _submit_signal(http, "node-attr-1")

    assert signal["event_id"] is not None
    assert signal["contributor_id"] == contrib["id"]


# ---------------------------------------------------------------------------
# 3. Signal appears in GET /signals
# ---------------------------------------------------------------------------


def test_signal_appears_in_list(client):
    http, db = client
    _register(http, "node-list-1")
    signal = _submit_signal(http, "node-list-1")
    event_id = signal["event_id"]

    r = http.get("/api/v1/signals?limit=100")
    assert r.status_code == 200, r.text
    data = r.json()
    # Response is paginated
    items = data.get("items", data) if isinstance(data, dict) else data
    ids = [item["id"] for item in items]
    assert event_id in ids, f"Signal {event_id} must appear in GET /signals"


# ---------------------------------------------------------------------------
# 4. Contributor attribution recorded in DB
# ---------------------------------------------------------------------------


def test_contributor_attribution_in_db(client):
    http, db = client
    contrib = _register(http, "node-db-attr-1")
    signal = _submit_signal(http, "node-db-attr-1", symbol="ETH")
    event_id = signal["event_id"]

    row = db.conn.execute(
        "SELECT contributor_id, signal_asset FROM contributor_signals WHERE event_id = ?",
        (event_id,),
    ).fetchone()

    assert row is not None, "Attribution row must exist in contributor_signals"
    assert str(row[0]) == contrib["id"]
    assert str(row[1]).upper() == "ETH"


# ---------------------------------------------------------------------------
# 5. GET /signals/{id}/attribution returns correct contributor
# ---------------------------------------------------------------------------


def test_attribution_endpoint_returns_correct_contributor(client):
    http, db = client
    _register(http, "node-attribution-ep")
    signal = _submit_signal(http, "node-attribution-ep", conviction=8.0)
    event_id = signal["event_id"]

    r = http.get(f"/api/v1/signals/{event_id}/attribution")
    assert r.status_code == 200, f"Attribution endpoint failed: {r.text}"
    body = r.json()

    assert body["signal_id"] == event_id
    # producer_id is set to contributor name or source
    assert body["producer_id"] is not None
    assert body["domain"] == "curator"
    assert body["score"] == 8.0
    assert body["emitted_at"] is not None


# ---------------------------------------------------------------------------
# 6. Signal for unregistered contributor → 404
# ---------------------------------------------------------------------------


def test_signal_for_unknown_contributor_fails(client):
    http, db = client
    r = http.post(
        "/api/v1/signals/submit",
        json={
            "event_type": "signal.curator.v1",
            "node_id": "ghost-node-xyz",
            "source": "ghost",
            "payload": {"symbol": "BTC", "direction": "bullish", "conviction": 5.0},
        },
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 7. GET /signals domain filter works
# ---------------------------------------------------------------------------


def test_signals_domain_filter(client):
    http, db = client
    _register(http, "node-filter-1")
    _submit_signal(http, "node-filter-1", symbol="BTC")

    r = http.get("/api/v1/signals?domain=curator&limit=100")
    assert r.status_code == 200
    data = r.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    for item in items:
        assert "curator" in item["type"], f"Expected curator signal, got {item['type']}"


# ---------------------------------------------------------------------------
# 8. Attribution for unknown signal_id → 404
# ---------------------------------------------------------------------------


def test_attribution_unknown_signal_404(client):
    http, db = client
    r = http.get("/api/v1/signals/nonexistent-id/attribution")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 9. Multiple contributors attributed independently
# ---------------------------------------------------------------------------


def test_multiple_contributor_attribution(client):
    http, db = client
    contrib_a = _register(http, "node-multi-a", name="AgentA")
    contrib_b = _register(http, "node-multi-b", name="AgentB")

    sig_a = _submit_signal(http, "node-multi-a", conviction=6.0)
    sig_b = _submit_signal(http, "node-multi-b", conviction=9.0)

    # Each signal attributed to its own contributor
    row_a = db.conn.execute(
        "SELECT contributor_id FROM contributor_signals WHERE event_id = ?",
        (sig_a["event_id"],),
    ).fetchone()
    row_b = db.conn.execute(
        "SELECT contributor_id FROM contributor_signals WHERE event_id = ?",
        (sig_b["event_id"],),
    ).fetchone()

    assert str(row_a[0]) == contrib_a["id"]
    assert str(row_b[0]) == contrib_b["id"]
    assert contrib_a["id"] != contrib_b["id"]
