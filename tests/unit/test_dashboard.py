from __future__ import annotations

from dataclasses import dataclass

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

    # used by config_page
    def _get_json(self, path: str, params: dict | None = None) -> _Res:
        return _Res({}, False)


def test_dashboard_routes_200() -> None:
    with TestClient(app) as client:
        client.app.state.api_client = DummyApiClient()

        routes = [
            "/",
            "/home",
            "/positions",
            "/signals",
            "/social",
            "/performance",
            "/system",
            "/config",
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
        ]

        for r in routes:
            resp = client.get(r)
            assert resp.status_code == 200, r
