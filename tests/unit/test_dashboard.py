from __future__ import annotations

import io
from dataclasses import dataclass
from unittest.mock import patch

from fastapi.testclient import TestClient

from dashboard.app import app


@dataclass
class _Res:
    data: object
    ok: bool


# "The map is not the territory. The backtest is not the trade."
# DummyApiClient is the map. The real client is the trade.
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

    def run_brain_cycle(self) -> _Res:
        return _Res({"cycle_id": "cycle-test"}, True)

    def set_kill_switch(self, level: int, reason: str = "dashboard") -> _Res:
        return _Res({"level": level, "reason": reason}, True)

    def get_karma_summary(self) -> _Res:
        return _Res({"pending_intents": 0, "percentage": 0.005, "treasury_address": "0x0", "receipts": 0}, False)

    def get_karma_intents(self) -> _Res:
        return _Res({"items": []}, False)

    def get_karma_receipts(self) -> _Res:
        return _Res({"items": []}, False)

    def get_social_status(self) -> _Res:
        return _Res(
            {
                "pipeline_status": "active",
                "diagnosis": "Running",
                "producers": [],
                "watchlist": [],
                "watchlist_count": 0,
                "sources_configured": 0,
                "seeded": False,
                "actions_available": ["run_now"],
                "pipeline_active": True,
            },
            False,
        )

    def get_social_watchlist(self) -> _Res:
        return _Res({"watchlist": [], "count": 0}, False)

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

    def get_collector_health(self) -> _Res:
        return _Res({"collectors": [], "summary": {}}, False)

    def get_convictions(self, limit: int = 20) -> _Res:
        return _Res({"items": []}, False)

    def get_artifacts(self, limit: int = 20) -> _Res:
        return _Res({"items": []}, False)

    # used by config_page
    def _get_json(self, path: str, params: dict | None = None) -> _Res:
        return _Res({}, False)


_FAKE_TICKER = b'{"bitcoin":{"usd":80000,"usd_24h_change":1.5},"ethereum":{"usd":3000,"usd_24h_change":-0.5},"solana":{"usd":150,"usd_24h_change":2.1}}'


def test_dashboard_routes_200() -> None:
    mock_resp = io.BytesIO(_FAKE_TICKER)
    with patch("urllib.request.urlopen", return_value=mock_resp), TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()

        routes = [
            "/",
            "/home",
            "/positions",
            "/signals",
            "/social",
            "/performance",
            "/settings",
            "/treasury",
            # partials used by templates
            "/partials/kill-dot",
            "/partials/regime-pill",
            "/partials/regime-banner",
            "/partials/positions",
            "/partials/position/HL-001",
            "/partials/conviction",
            "/partials/signal-feed",
            "/partials/system-status",
            "/partials/producers",
            "/partials/kill-switch",
            "/partials/sentiment-map",
            "/partials/social-alerts",
            "/partials/curator-feed",
            "/partials/karma-intents",
            "/partials/signal-history",
            "/partials/signal-history?domain=ta",
            "/api/market-ticker",
        ]

        for r in routes:
            resp = client.get(r)
            assert resp.status_code == 200, r

        # /system and /config redirect to /settings (302)
        for r in ["/system", "/config"]:
            resp = client.get(r, follow_redirects=False)
            assert resp.status_code == 302, f"{r} should redirect"
            assert resp.headers["location"] == "/settings"


def test_dashboard_brain_controls_no_dead_routes() -> None:
    with TestClient(app) as client:
        dummy = DummyApiClient()
        client.app.state.api_client = dummy
        client.app.state.kill_switch_api_client = dummy

        run_resp = client.post("/api/v1/brain/run")
        assert run_resp.status_code == 200
        assert "Cycle triggered" in run_resp.text

        kill_resp = client.post("/api/kill-switch?level=2")
        assert kill_resp.status_code == 200
        assert "Kill switch set to L2" in kill_resp.text


def test_settings_actions_are_truthful_and_config_paths_exist() -> None:
    with TestClient(app) as client:
        dummy = DummyApiClient()
        client.app.state.api_client = dummy
        client.app.state.kill_switch_api_client = dummy

        actions: list[tuple[str, str, dict[str, str] | None]] = [
            ("post", "/api/settings/trading-mode", {"mode": "live"}),
            ("post", "/api/settings/risk/max_daily_loss", {"value": "500"}),
            ("post", "/api/settings/reset-defaults", None),
            ("post", "/api/settings/clear-signals", None),
            ("post", "/api/settings/config/preset", {"preset": "balanced"}),
            ("get", "/api/settings/config/reload", None),
            ("post", "/api/settings/config/save", {"execution.mode": "paper"}),
        ]

        for method, path, payload in actions:
            if method == "get":
                resp = client.get(path)
            else:
                resp = client.post(path, data=payload or {})
            assert resp.status_code == 200
            body = resp.text.lower()
            assert "not implemented" in body
            assert "saved" not in body
            assert "restored" not in body
            assert "cleared" not in body

        page = client.get("/settings")
        assert page.status_code == 200
        assert "/api/config" not in page.text
        assert "/api/settings/config/save" in page.text


class SignalTimelineApiClient(DummyApiClient):
    def get_signals(self, domain: str | None = None) -> _Res:
        return _Res(
            {
                "items": [
                    {
                        "type": "signal.ta.rsi.v1",
                        "ts": "2026-03-12T18:00:00Z",
                        "payload": {"symbol": "BTC", "desc": "RSI oversold", "score": 7.2, "direction": "▲"},
                    },
                    {
                        "type": "signal.social.sentiment.v1",
                        "ts": "2026-03-12T19:00:00Z",
                        "payload": {"symbol": "SOL", "desc": "Social velocity", "score": 6.4, "direction": "▲"},
                    },
                ],
                "total": 2,
            },
            True,
        )


class SocialPanelApiClient(DummyApiClient):
    def get_social_status(self) -> _Res:
        return _Res(
            {
                "pipeline_status": "active",
                "diagnosis": "Running",
                "producers": [],
                "watchlist": [],
                "watchlist_count": 2,
                "sources_configured": 4,
                "signal_events_count": 12,
                "seeded": True,
                "actions_available": ["run_now"],
                "pipeline_active": True,
            },
            True,
        )

    def get_social_sentiment(self) -> _Res:
        return _Res({"items": [{"symbol": "SOL", "score": 0.4, "label": "bull"}]}, True)

    def get_social_alerts(self) -> _Res:
        return _Res(
            {
                "items": [
                    {
                        "type": "velocity",
                        "symbol": "SOL",
                        "desc": "Velocity accelerating",
                    }
                ]
            },
            True,
        )


# Popper: if a timeline survives only pretty formatting, it fails falsification.
# Pin chart placement to raw event time, not display cosmetics.
def test_signals_page_uses_raw_timestamps_for_timeline() -> None:
    with TestClient(app) as client:
        client.app.state.api_client = SignalTimelineApiClient()
        resp = client.get("/signals")
        assert resp.status_code == 200
        # Raw ISO timestamps must be present for timeline placement JS.
        assert "2026-03-12T18:00:00Z" in resp.text
        assert "2026-03-12T19:00:00Z" in resp.text


def test_sentiment_map_partial_shows_live_source_counts() -> None:
    with TestClient(app) as client:
        client.app.state.api_client = SocialPanelApiClient()
        resp = client.get("/partials/sentiment-map")
        assert resp.status_code == 200
        assert "Sources configured: 4" in resp.text
        assert "Signal events: 12" in resp.text


def test_social_alerts_partial_falls_back_to_symbol() -> None:
    with TestClient(app) as client:
        client.app.state.api_client = SocialPanelApiClient()
        resp = client.get("/partials/social-alerts")
        assert resp.status_code == 200
        assert ">SOL<" in resp.text


def test_social_page_preserves_contextual_headers_on_htmx_refresh() -> None:
    with TestClient(app) as client:
        client.app.state.api_client = SocialPanelApiClient()
        resp = client.get("/social")
        assert resp.status_code == 200
        assert "Pipeline Status" in resp.text
        assert "Collector Health" in resp.text
        assert 'id="social-status-refresh"' in resp.text
        assert 'id="collector-health-refresh"' in resp.text
