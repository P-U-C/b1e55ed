from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ApiResult:
    data: Any
    ok: bool


class ApiClient:
    """Very small sync HTTP client for the API layer.

    All methods are best-effort: on any failure they return an empty-ish value
    so the dashboard can degrade gracefully.
    """

    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._timeout = httpx.Timeout(10.0)
        self._long_timeout = httpx.Timeout(60.0)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self._timeout,
            headers=headers,
        )

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> ApiResult:
        try:
            resp = self._client.get(path, params=params)
            resp.raise_for_status()
            return ApiResult(resp.json(), True)
        except Exception:
            return ApiResult(None, False)

    # GET is observation. POST is intervention.
    # Heisenberg's dashboard: the moment you seed the watchlist, you change what you're watching.
    def _post_json(self, path: str, body: dict[str, Any] | None = None) -> ApiResult:
        try:
            resp = self._client.post(path, json=body or {})
            resp.raise_for_status()
            return ApiResult(resp.json(), True)
        except Exception:
            return ApiResult(None, False)

    def _patch_json(self, path: str, body: dict[str, Any] | None = None) -> ApiResult:
        try:
            resp = self._client.patch(path, json=body or {})
            resp.raise_for_status()
            return ApiResult(resp.json(), True)
        except Exception:
            return ApiResult(None, False)

    def _delete_json(self, path: str) -> ApiResult:
        try:
            resp = self._client.delete(path)
            resp.raise_for_status()
            return ApiResult(resp.json(), True)
        except Exception:
            return ApiResult(None, False)

    # ---- Brain / system -------------------------------------------------

    def get_cockpit_state(self) -> ApiResult:
        return self._get_json("/cockpit/state")

    def get_positions(self) -> ApiResult:
        return self._get_json("/positions")

    def get_signals(self, domain: str | None = None, hours: int = 24) -> ApiResult:
        params: dict[str, Any] = {"limit": 500, "offset": 0, "hours": hours, "timeline": "true"}
        if domain:
            params["domain"] = domain
        return self._get_json("/signals", params=params)

    def get_universe_packs(self) -> ApiResult:
        return self._get_json("/universe/packs")

    def get_universe_bundles(self) -> ApiResult:
        return self._get_json("/universe/bundles")

    def get_universe_active(self) -> ApiResult:
        return self._get_json("/universe/active")

    def create_universe_bundle(self, body: dict[str, Any]) -> ApiResult:
        return self._post_json("/universe/bundles", body)

    def update_universe_bundle(self, bundle_id: str, body: dict[str, Any]) -> ApiResult:
        return self._patch_json(f"/universe/bundles/{bundle_id}", body)

    def delete_universe_bundle(self, bundle_id: str) -> ApiResult:
        return self._delete_json(f"/universe/bundles/{bundle_id}")

    def get_producers_status(self) -> ApiResult:
        return self._get_json("/producers/status")

    def get_regime(self) -> ApiResult:
        return self._get_json("/regime")

    def get_kill_switch(self) -> ApiResult:
        # Kill switch is exposed via brain/status.
        return self._get_json("/brain/status")

    def run_brain_cycle(self) -> ApiResult:
        url = f"{self.base_url}/brain/run"
        try:
            with httpx.Client(timeout=self._long_timeout, headers=self._headers()) as client:
                resp = client.post(url, json={})
                resp.raise_for_status()
                return ApiResult(resp.json(), True)
        except Exception as exc:
            logger.warning("run_brain_cycle failed: %s", exc)
            return ApiResult(None, False)

    def set_kill_switch(self, level: int, reason: str = "dashboard") -> ApiResult:
        return self._post_json("/kill-switch/set", {"level": int(level), "reason": reason})

    def get_convictions(self, limit: int = 20) -> ApiResult:
        return self._get_json(f"/brain/convictions?limit={limit}")

    # ---- Karma ----------------------------------------------------------

    def get_karma_summary(self) -> ApiResult:
        # API exposes treasury summary at /treasury
        return self._get_json("/treasury")

    def get_karma_intents(self) -> ApiResult:
        return self._get_json("/karma/intents")

    def get_karma_receipts(self) -> ApiResult:
        return self._get_json("/karma/receipts")

    # ---- Social (best-effort; routes may not exist yet) -----------------

    def get_social_sentiment(self) -> ApiResult:
        return self._get_json("/social/sentiment")

    def get_social_alerts(self) -> ApiResult:
        return self._get_json("/social/alerts")

    def get_social_narratives(self) -> ApiResult:
        return self._get_json("/social/narratives")

    def get_social_sources(self) -> ApiResult:
        return self._get_json("/social/sources")

    def get_curator_feed(self) -> ApiResult:
        return self._get_json("/social/curator-feed")

    # ---- Artifacts ------------------------------------------------------

    def get_artifacts(self, limit: int = 20) -> ApiResult:
        return self._get_json("/artifacts/", params={"limit": limit})

    def get_social_status(self) -> ApiResult:
        return self._get_json("/social/status")

    def get_social_watchlist(self) -> ApiResult:
        return self._get_json("/social/watchlist")

    def post_social_seed(self, watchlist: list[str] | None = None) -> ApiResult:
        body: dict[str, Any] = {}
        if watchlist:
            body["watchlist"] = watchlist
        return self._post_json("/social/seed", body)

    def post_social_reset_failures(self) -> ApiResult:
        return self._post_json("/social/reset-failures", {})

    def post_social_run_now(self) -> ApiResult:
        return self._post_json("/social/run-now", {})

    def post_social_add_watchlist(self, symbol: str) -> ApiResult:
        return self._post_json("/social/watchlist/add", {"symbol": symbol})

    def post_social_add_source(self, name: str, type: str, value: str) -> ApiResult:
        return self._post_json("/social/sources/add", {"name": name, "type": type, "value": value})

    def get_collector_health(self) -> ApiResult:
        return self._get_json("/social/collector-health")

    def delete_social_watchlist(self, symbol: str) -> ApiResult:
        return self._delete_json(f"/social/watchlist/{symbol}")
