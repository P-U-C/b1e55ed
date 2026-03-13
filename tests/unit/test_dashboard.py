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
        payload = {"id": bundle_id, **body}
        return _Res(payload, True)

    def delete_universe_bundle(self, bundle_id: str) -> _Res:
        return _Res({"ok": True, "deleted": bundle_id}, True)

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
            "/partials/universe-bundles",
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


class UniverseDashboardApiClient(DummyApiClient):
    def __init__(self) -> None:
        self.bundles = [
            {
                "id": "crypto-core",
                "name": "Crypto Core",
                "symbols": ["BTC", "ETH"],
                "tags": ["starter", "crypto", "beta"],
                "asset_class": "crypto",
                "venue": "global",
                "enabled": True,
                "source": "wizard",
            },
            {
                "id": "tradfi-infra",
                "name": "TradFi Infra",
                "symbols": ["SPY"],
                "tags": ["starter", "tradfi", "rates"],
                "asset_class": "tradfi",
                "venue": "nyse",
                "enabled": True,
                "source": "wizard",
            },
        ]
        self.packs = [
            {
                "id": "tradfi-infra",
                "name": "TradFi Infra",
                "mapping_summary": {"direct": 3, "proxy": 0},
            },
            {
                "id": "hl-tradfi-perps",
                "name": "Hyperliquid TradFi-Perps",
                "mapping_summary": {"direct": 3, "proxy": 1},
            },
            {
                "id": "mixed-market",
                "name": "Mixed Market",
                "mapping_summary": {"direct": 3, "proxy": 2},
            },
        ]

    def _active_symbols(self) -> list[str]:
        out: list[str] = []
        for bundle in self.bundles:
            if not bundle.get("enabled", True):
                continue
            for sym in bundle.get("symbols", []):
                s = str(sym).upper()
                if s not in out:
                    out.append(s)
        return out

    def _asset_class_map(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for bundle in self.bundles:
            if not bundle.get("enabled", True):
                continue
            key = str(bundle.get("asset_class") or "").strip()
            if not key:
                continue
            out.setdefault(key, [])
            for sym in bundle.get("symbols", []):
                s = str(sym).upper()
                if s not in out[key]:
                    out[key].append(s)
        return out

    def _venue_map(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for bundle in self.bundles:
            if not bundle.get("enabled", True):
                continue
            key = str(bundle.get("venue") or "").strip()
            if not key:
                continue
            out.setdefault(key, [])
            for sym in bundle.get("symbols", []):
                s = str(sym).upper()
                if s not in out[key]:
                    out[key].append(s)
        return out

    def _tag_map(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for bundle in self.bundles:
            if not bundle.get("enabled", True):
                continue
            symbols = [str(sym).upper() for sym in bundle.get("symbols", [])]
            for tag in bundle.get("tags", []):
                key = str(tag).strip().lower()
                if not key:
                    continue
                out.setdefault(key, [])
                for sym in symbols:
                    if sym not in out[key]:
                        out[key].append(sym)
        return out

    def get_universe_packs(self) -> _Res:
        return _Res({"items": self.packs, "total": len(self.packs)}, True)

    def get_universe_bundles(self) -> _Res:
        return _Res({"items": self.bundles, "total": len(self.bundles)}, True)

    def get_universe_active(self) -> _Res:
        return _Res(
            {
                "symbols": self._active_symbols(),
                "count": len(self._active_symbols()),
                "fallback_to_symbols": False,
                "bundles": self.bundles,
                "enabled_bundle_ids": [str(b["id"]) for b in self.bundles if b.get("enabled", True)],
                "asset_classes": sorted(self._asset_class_map().keys()),
                "venues": sorted(self._venue_map().keys()),
                "tags": sorted(self._tag_map().keys()),
                "asset_class_symbols": self._asset_class_map(),
                "venue_symbols": self._venue_map(),
                "tag_symbols": self._tag_map(),
            },
            True,
        )

    def get_signals(self, domain: str | None = None) -> _Res:
        items = [
            {
                "type": "signal.ta.rsi.v1",
                "payload": {"symbol": "BTC", "message": "BTC momentum"},
                "ts": "2026-03-12T20:00:00+00:00",
            },
            {
                "type": "signal.tradfi.v1",
                "payload": {"symbol": "SPY", "message": "SPY basis", "venue": "nyse"},
                "ts": "2026-03-12T20:05:00+00:00",
            },
        ]
        if domain:
            items = [it for it in items if str(it.get("type", "")).startswith(f"signal.{domain}")]
        return _Res({"items": items, "total": len(items), "limit": 100, "offset": 0}, True)

    def create_universe_bundle(self, body: dict) -> _Res:
        pack_id = str(body.get("pack_id") or "").strip().lower()

        if pack_id == "hl-tradfi-perps":
            default_name = "Hyperliquid TradFi-Perps"
            default_symbols = ["HYPE", "SOL", "BTC", "ETH"]
            default_tags = ["starter", "hyperliquid", "tradfi", "vol", "pack:hl-tradfi-perps"]
            default_asset_class = "crypto"
            default_venue = "hyperliquid"
        elif pack_id == "tradfi-infra":
            default_name = "TradFi Infra"
            default_symbols = ["BTC", "ETH", "SOL"]
            default_tags = ["starter", "tradfi", "rates", "pack:tradfi-infra"]
            default_asset_class = "tradfi"
            default_venue = "binance"
        else:
            default_name = "Bundle"
            default_symbols = []
            default_tags = []
            default_asset_class = "crypto"
            default_venue = "global"

        name = str(body.get("name") or default_name).strip() or default_name
        symbols_raw = body.get("symbols") or default_symbols
        tags_raw = body.get("tags") or default_tags

        slug = pack_id or name.lower().replace(" ", "-")
        bundle = {
            "id": slug,
            "name": name,
            "symbols": [str(s).upper() for s in symbols_raw],
            "tags": [str(t) for t in tags_raw],
            "asset_class": body.get("asset_class") or default_asset_class,
            "venue": body.get("venue") or default_venue,
            "enabled": bool(body.get("enabled", True)),
            "source": body.get("source") or "user",
        }
        self.bundles.append(bundle)
        return _Res(bundle, True)

    def update_universe_bundle(self, bundle_id: str, body: dict) -> _Res:
        for bundle in self.bundles:
            if bundle["id"] == bundle_id:
                bundle.update(body)
                return _Res(bundle, True)
        return _Res({}, False)

    def delete_universe_bundle(self, bundle_id: str) -> _Res:
        self.bundles = [b for b in self.bundles if b["id"] != bundle_id]
        return _Res({"ok": True, "deleted": bundle_id}, True)


def test_signals_page_filters_by_bundle_asset_class_and_tag() -> None:
    with TestClient(app) as client:
        client.app.state.api_client = UniverseDashboardApiClient()

        by_bundle = client.get("/signals?bundle=crypto-core")
        assert by_bundle.status_code == 200
        assert "BTC momentum" in by_bundle.text
        assert "SPY basis" not in by_bundle.text

        by_asset_class = client.get("/signals?asset_class=tradfi")
        assert by_asset_class.status_code == 200
        assert "SPY basis" in by_asset_class.text
        assert "BTC momentum" not in by_asset_class.text

        by_tag = client.get("/signals?tag=rates")
        assert by_tag.status_code == 200
        assert "SPY basis" in by_tag.text
        assert "BTC momentum" not in by_tag.text


def test_settings_universe_bundle_controls_use_live_routes() -> None:
    with TestClient(app) as client:
        client.app.state.api_client = UniverseDashboardApiClient()

        add_pack_resp = client.post(
            "/api/settings/universe/bundles",
            data={
                "pack_id": "hl-tradfi-perps",
                "enabled": "true",
            },
        )
        assert add_pack_resp.status_code == 200
        assert "Added bundle: Hyperliquid TradFi-Perps" in add_pack_resp.text

        add_resp = client.post(
            "/api/settings/universe/bundles",
            data={
                "name": "Meme Basket",
                "symbols": "DOGE,PEPE",
                "tags": "meme",
                "asset_class": "crypto",
                "venue": "global",
                "enabled": "true",
            },
        )
        assert add_resp.status_code == 200
        assert "Added bundle: Meme Basket" in add_resp.text

        toggle_resp = client.post(
            "/api/settings/universe/bundles/meme-basket/toggle",
            data={"enabled": "false"},
        )
        assert toggle_resp.status_code == 200
        assert "meme-basket disabled" in toggle_resp.text

        delete_resp = client.post("/api/settings/universe/bundles/meme-basket/delete")
        assert delete_resp.status_code == 200
        assert "Deleted bundle: meme-basket" in delete_resp.text


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


class SignalEpochApiClient(DummyApiClient):
    def get_signals(self, domain: str | None = None) -> _Res:
        return _Res(
            {
                "items": [
                    {
                        "type": "signal.ta.rsi.v1",
                        "ts": 1741880000,
                        "payload": {"symbol": "BTC", "desc": "Epoch ts", "score": 7.0, "direction": "▲"},
                    }
                ],
                "total": 1,
            },
            True,
        )


def test_signals_page_emits_epoch_ms_for_timeline() -> None:
    with TestClient(app) as client:
        client.app.state.api_client = SignalEpochApiClient()
        resp = client.get("/signals")
        assert resp.status_code == 200
        assert "1741880000000" in resp.text


class PositionsConflictApiClient(DummyApiClient):
    def get_positions(self) -> _Res:
        return _Res(
            [
                {
                    "id": "HL-123",
                    "symbol": "BTC",
                    "direction": "short",
                    "entry_price": 100,
                    "stop_loss": 110,
                    "take_profit": 90,
                    "size_notional": -1000,
                    "leverage": 2,
                    "status": "open",
                }
            ],
            True,
        )

    def get_convictions(self, limit: int = 20) -> _Res:
        return _Res({"items": [{"symbol": "BTC", "direction": "bullish", "confidence": 0.8, "ts": "2026-03-12T19:00:00Z"}]}, True)


def test_positions_page_short_loss_uses_red_and_shows_conflict_badge() -> None:
    with patch("dashboard.app._latest_mark_prices", return_value={"BTC": 110.0}), TestClient(app) as client:
        client.app.state.api_client = PositionsConflictApiClient()
        resp = client.get("/positions?view=open")
        assert resp.status_code == 200
        assert "⚠ conviction conflict" in resp.text
        assert "$-100" in resp.text
        assert "$+100" not in resp.text
