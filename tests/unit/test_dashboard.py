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
