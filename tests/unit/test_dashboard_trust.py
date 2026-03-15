"""Tests for dashboard trust and refresh fixes.

P2-1: Settings controls that are not yet implemented should be visually
      disabled and carry a "Not yet available" tooltip so operators are
      not misled into thinking they can change live config from the UI.

P2-3: The hash-chain verify endpoint uses fast=True (recent events only),
      so the success message must say "recent events / fast mode", not
      "N events checked", to avoid implying a full audit was performed.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

from fastapi.testclient import TestClient

from dashboard.app import app
from tests.unit.test_dashboard import DummyApiClient

# ---------------------------------------------------------------------------
# P2-1 — Settings controls disabled when not implemented
# ---------------------------------------------------------------------------


def test_settings_controls_disabled_when_unimplemented() -> None:
    """All 'not yet implemented' settings controls must have disabled attr
    and a 'Not yet available' tooltip so operators are not misled."""
    with TestClient(app) as client:
        stub = DummyApiClient()
        client.app.state.api_client = stub
        client.app.state.kill_switch_api_client = stub
        resp = client.get("/settings")

    assert resp.status_code == 200
    html = resp.text

    # Every unimplemented button/select must carry the 'Not yet available' tooltip
    assert 'title="Not yet available"' in html, "Settings page must have at least one title='Not yet available' tooltip on a disabled control"

    # Controls should have cursor:not-allowed to visually signal they are disabled
    assert "cursor:not-allowed" in html, "Disabled controls should have cursor:not-allowed styling"

    # Unimplemented routes should still be present in the HTML (routes kept)
    # but the controls pointing to them must be disabled
    unimplemented_routes = [
        "/api/settings/config/preset",
        "/api/settings/config/reload",
        "/api/settings/config/save",
        "/api/settings/clear-signals",
        "/api/settings/reset-defaults",
    ]
    for route in unimplemented_routes:
        assert route in html, f"Route {route} should still be referenced in UI"

    # All hx-post/hx-get elements targeting unimplemented routes should
    # have the disabled attribute before the closing >
    import re

    # Find all tag fragments that reference an unimplemented route
    for route in unimplemented_routes:
        # Grab the raw tag text surrounding each route reference
        pattern = re.compile(
            r"<(?:button|select|input|a)[^>]*" + re.escape(route) + r"[^>]*>",
            re.DOTALL,
        )
        matches = pattern.findall(html)
        for match in matches:
            assert "disabled" in match, f"Element pointing to {route} must have 'disabled' attribute; got: {match!r}"


# ---------------------------------------------------------------------------
# P2-3 — Fast verify message accurately describes partial scope
# ---------------------------------------------------------------------------


def test_dashboard_fast_verify_message_mentions_partial_scope(tmp_path) -> None:
    """The /api/events/verify-chain endpoint uses fast=True so its success
    message must NOT claim all events were checked.  It must mention
    'fast mode' or 'recent events' and point operators to the CLI for a
    full audit."""
    # Build a tiny brain.db with a couple of events so the count query works
    db_path = tmp_path / "brain.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE events (
            id TEXT PRIMARY KEY,
            hash TEXT,
            prev_hash TEXT,
            ts TEXT,
            type TEXT,
            payload TEXT
        )"""
    )
    conn.execute("INSERT INTO events VALUES ('e1','abc','','2026-01-01T00:00:00Z','test','{}')")
    conn.execute("INSERT INTO events VALUES ('e2','def','abc','2026-01-01T00:01:00Z','test','{}')")
    conn.commit()
    conn.close()

    with patch("dashboard.app._get_brain_db", return_value=db_path), patch(
        "engine.core.database.Database.verify_hash_chain",
        return_value=True,
    ), TestClient(app) as client:
        stub = DummyApiClient()
        client.app.state.api_client = stub
        client.app.state.kill_switch_api_client = stub
        resp = client.post("/api/events/verify-chain")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.text.lower()

    # Must NOT claim all events were checked when only fast mode ran
    assert "events checked" not in body, f"fast=True verify must not claim all events were checked; got: {resp.text!r}"

    # Must mention partial / fast scope
    assert any(phrase in body for phrase in ("fast mode", "recent events", "partial", "cli")), (
        f"Verify message must mention partial scope or point to CLI; got: {resp.text!r}"
    )
