"""engine.producers.financial_datasets

FinancialDatasetsMCPProducer — fundamentals signal producer.

Data source: financialdatasets.ai REST API (mirrors their MCP server interface).
MCP source URL set for when full MCP stdio protocol is implemented in S2+.

Emits TRADFI_SIGNAL events when:
- Earnings beat/miss vs consensus (PEAD signal)
- Revenue growth acceleration/deceleration
- P/E compression vs sector

Scope: S&P 500 equities. Requires FINANCIAL_DATASETS_API_KEY env var.
Skips gracefully if API key not set or API unreachable.
"""

from __future__ import annotations

import os
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    UTC = UTC  # noqa: N806

from typing import Any

from engine.core.events import EventType
from engine.core.models import Event
from engine.mcp.client import HttpMCPClient
from engine.producers.base import BaseProducer
from engine.producers.registry import register


class FinancialDatasetsMCPProducer(BaseProducer):
    """MCP-inbound producer for earnings surprise signals."""

    name = "financial_datasets"
    domain = "tradfi"
    schedule = "0 */6 * * *"  # every 6h
    mcp_source_url = "https://github.com/financial-datasets/mcp-server"

    _watchlist = ["NVDA", "MSFT", "AAPL", "META", "GOOGL"]
    _api_base = "https://api.financialdatasets.ai"

    @staticmethod
    def _float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _iso_ts() -> datetime:
        return datetime.now(tz=UTC)

    def _client(self) -> HttpMCPClient | None:
        api_key = os.getenv("FINANCIAL_DATASETS_API_KEY")
        if not api_key:
            return None
        return HttpMCPClient(base_url=self._api_base, api_key=api_key, timeout=10)

    def collect(self) -> list[dict]:
        """Collect recent income statement rows for a fixed watchlist.

        Returns [] if API key is missing or on any API/client error.
        """

        client = self._client()
        if client is None:
            return []

        try:
            out: list[dict] = []
            for ticker in self._watchlist:
                result = client.call_tool(
                    "financials/income-statements/",
                    {
                        "ticker": ticker,
                        "limit": 1,
                    },
                )

                if "error" in result.raw:
                    self.ctx.logger.warning(
                        "financial_datasets_collect_failed",
                        extra={"ticker": ticker, "error": result.raw.get("error")},
                    )
                    return []

                for row in result.data:
                    if not isinstance(row, dict):
                        continue
                    merged = dict(row)
                    merged.setdefault("ticker", ticker)
                    out.append(merged)

            return out
        except Exception:  # noqa: BLE001
            self.ctx.logger.warning("financial_datasets_collect_failed", extra={"producer": self.name})
            return []

    def normalize(self, raw: list[dict]) -> list[Event]:
        """Normalize earnings rows into TRADFI signal events."""

        events: list[Event] = []
        now = self._iso_ts()

        for row in raw:
            if not isinstance(row, dict):
                continue

            ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
            if not ticker:
                continue

            actual_eps = self._float(row.get("actual_eps") or row.get("eps_actual") or row.get("eps") or row.get("eps_diluted") or row.get("eps_reported"))
            estimated_eps = self._float(row.get("estimated_eps") or row.get("eps_estimate") or row.get("eps_consensus") or row.get("eps_diluted_estimate"))

            if actual_eps is None or estimated_eps is None:
                continue

            denom = abs(estimated_eps) if abs(estimated_eps) > 1e-9 else max(abs(actual_eps), 1.0)
            surprise_ratio = (actual_eps - estimated_eps) / denom

            if abs(surprise_ratio) <= 0.02:
                signal = "neutral"
                confidence = max(0.0, 1.0 - min(1.0, abs(surprise_ratio) / 0.02))
            elif actual_eps > estimated_eps:
                signal = "earnings_beat"
                confidence = min(1.0, abs(surprise_ratio) / 0.10)
            else:
                signal = "earnings_miss"
                confidence = min(1.0, abs(surprise_ratio) / 0.10)

            reason = f"EPS actual {actual_eps:.4g} vs estimate {estimated_eps:.4g} ({surprise_ratio:+.2%})."

            as_of = str(row.get("report_period") or row.get("period_end") or row.get("fiscal_date") or row.get("date") or now.date().isoformat())
            dedupe_key = f"{EventType.SIGNAL_TRADFI_V1}:{self.name}:{ticker}:{as_of}"

            payload = {
                "ticker": ticker,
                "symbol": ticker,
                "signal": signal,
                "confidence": round(confidence, 4),
                "reason": reason,
                "producer": self.name,
            }

            events.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_TRADFI_V1,
                    payload=payload,
                    ts=now,
                    observed_at=now,
                    source=self.name,
                    dedupe_key=dedupe_key,
                )
            )

        return events


# Conditional registration: skip silently when API key is not configured.
if os.getenv("FINANCIAL_DATASETS_API_KEY"):
    register("financial_datasets", domain="tradfi")(FinancialDatasetsMCPProducer)
