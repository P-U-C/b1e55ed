from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


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
        self._timeout = httpx.Timeout(2.0)

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> ApiResult:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self._timeout, headers=self._headers()) as client:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                return ApiResult(resp.json(), True)
        except Exception:
            return ApiResult(None, False)

    # ---- Brain / system -------------------------------------------------

    def get_positions(self) -> ApiResult:
        return self._get_json("/positions")

    def get_signals(self, domain: str | None = None) -> ApiResult:
        params: dict[str, Any] = {"limit": 100, "offset": 0}
        if domain:
            params["domain"] = domain
        return self._get_json("/signals", params=params)

    def get_producers_status(self) -> ApiResult:
        return self._get_json("/producers/status")

    def get_regime(self) -> ApiResult:
        return self._get_json("/regime")

    def get_kill_switch(self) -> ApiResult:
        # Kill switch is exposed via brain/status.
        return self._get_json("/brain/status")

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
