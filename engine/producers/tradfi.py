"""engine.producers.tradfi

TradFi Basis Producer.

Fetches carry/basis-style metrics (spot vs futures, funding proxy, OI changes)
from Binance public APIs and emits
:class:`~engine.core.events.EventType.SIGNAL_TRADFI_V1`.

Falls back to ``B1E55ED_TRADFI_BASIS_URL`` if that env var is set
(legacy path).

Easter egg:
- Markets rhyme; basis keeps the meter.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from engine.core.events import EventType, TradFiSignalPayload
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register

# ---------------------------------------------------------------------------
# Signal logic
# ---------------------------------------------------------------------------


def _compute_signal(
    basis_ann: float | None,
    funding_ann: float | None,
    meltup_score: float | None,
) -> tuple[str, float, str]:
    """Rule-based direction / confidence from TradFi metrics."""

    if meltup_score is not None and meltup_score == 4:
        return "long", 0.75, "meltup_score=4: full setup"

    if basis_ann is not None:
        if basis_ann > 8.0:
            return "short", 0.60, f"basis crowded ({basis_ann:.1f}% ann) \u2014 unwind risk"
        if basis_ann < 2.0 and (funding_ann is None or funding_ann < 0):
            return (
                "short",
                0.65,
                f"basis unwound ({basis_ann:.1f}%) + negative funding \u2014 risk_off",
            )
        if 3.0 <= basis_ann <= 6.0:
            if funding_ann is not None and 5.0 <= funding_ann <= 20.0:
                return "long", 0.55, f"basis healthy ({basis_ann:.1f}%) + funding normal"
            return "long", 0.45, f"basis healthy ({basis_ann:.1f}%) \u2014 early setup"

    return "flat", 0.0, "no clear regime signal"


# ---------------------------------------------------------------------------
# Binance helpers
# ---------------------------------------------------------------------------

_QUARTERLY_RE = re.compile(r"^(BTC|ETH)USD_\d{6}$")
_QUARTERLY_ASSETS = {"BTC", "ETH"}
_PERP_SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
_SPOT_SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}


def _days_to_expiry(symbol: str) -> float:
    """Parse YYMMDD from e.g. BTCUSD_250328 and return days to expiry."""
    suffix = symbol.split("_")[1]
    year = 2000 + int(suffix[:2])
    month = int(suffix[2:4])
    day = int(suffix[4:6])
    expiry = datetime(year, month, day, tzinfo=UTC)
    delta = (expiry - datetime.now(tz=UTC)).total_seconds() / 86400
    return max(delta, 1.0)


async def _fetch_binance(client: httpx.AsyncClient, universe: list[str]) -> list[dict[str, Any]]:
    """Fetch basis, funding, OI from Binance for each symbol in *universe*."""

    results: list[dict[str, Any]] = []

    # 1. Coin-M quarterly tickers (for BTC/ETH basis)
    quarterly_prices: dict[str, tuple[float, float]] = {}
    need_quarterly = [s for s in universe if s in _QUARTERLY_ASSETS]
    if need_quarterly:
        resp = await client.get("https://dapi.binance.com/dapi/v1/ticker/price", timeout=10)
        resp.raise_for_status()
        for tick in resp.json():
            sym = tick.get("symbol", "")
            if _QUARTERLY_RE.match(sym):
                asset = sym.split("USD_")[0]
                if asset in need_quarterly:
                    price = float(tick["price"])
                    days = _days_to_expiry(sym)
                    if asset not in quarterly_prices or days < quarterly_prices[asset][1]:
                        quarterly_prices[asset] = (price, days)

    # 2. Spot prices
    spot_prices: dict[str, float] = {}
    for asset in universe:
        spot_sym = _SPOT_SYMBOLS.get(asset)
        if not spot_sym:
            continue
        resp = await client.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": spot_sym},
            timeout=10,
        )
        resp.raise_for_status()
        spot_prices[asset] = float(resp.json()["price"])

    # 3. Funding rates
    funding_rates: dict[str, float] = {}
    for asset in universe:
        perp_sym = _PERP_SYMBOLS.get(asset)
        if not perp_sym:
            continue
        resp = await client.get(
            "https://fapi.binance.com/fapi/v1/fundingRate",
            params={"symbol": perp_sym, "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            rate = float(data[0]["fundingRate"])
            funding_rates[asset] = rate * 3 * 365 * 100

    # 4. Open interest
    oi_values: dict[str, float] = {}
    for asset in universe:
        perp_sym = _PERP_SYMBOLS.get(asset)
        if not perp_sym:
            continue
        resp = await client.get(
            "https://fapi.binance.com/fapi/v1/openInterest",
            params={"symbol": perp_sym},
            timeout=10,
        )
        resp.raise_for_status()
        oi_values[asset] = float(resp.json()["openInterest"])

    # 5. Assemble per-asset rows
    for asset in universe:
        row: dict[str, Any] = {"symbol": asset}

        if asset in quarterly_prices and asset in spot_prices:
            fut_price, days = quarterly_prices[asset]
            spot = spot_prices[asset]
            basis_pct = (fut_price / spot - 1) * 100
            row["basis_annualized"] = basis_pct * (365 / days)
        else:
            row["basis_annualized"] = None

        row["funding_annualized"] = funding_rates.get(asset)
        row["oi_change_pct"] = None
        row["oi_value"] = oi_values.get(asset)

        score = 0
        if row.get("basis_annualized") is not None and 3.0 <= row["basis_annualized"] <= 6.0:
            score += 1
        if row.get("funding_annualized") is not None and row["funding_annualized"] > 0:
            score += 1
        if row.get("funding_annualized") is not None and row["funding_annualized"] < 30:
            score += 1
        if oi_values.get(asset) is not None:
            score += 1
        row["meltup_score"] = score

        results.append(row)

    return results


def _dedupe_key(*, producer: str, symbol: str, ts: datetime) -> str:
    """Symbol + timestamp (+ producer) dedupe key."""
    return f"{EventType.SIGNAL_TRADFI_V1}:{producer}:{symbol}:{int(ts.timestamp())}"


@register("tradfi-basis", domain="tradfi")
class TradFiBasisProducer(BaseProducer):
    """Produce basis/carry signals for the configured universe."""

    schedule = "*/30 * * * *"
    mcp_source_url: str | None = None  # override with MCP server URL when available

    def _endpoint(self) -> str | None:
        return os.getenv("B1E55ED_TRADFI_BASIS_URL") or os.getenv("TRADFI_BASIS_URL")

    def collect(self) -> list[dict[str, Any]]:
        # Legacy fallback: if endpoint env var is set, use old HTTP path
        url = self._endpoint()
        if url:
            symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
            data: Any = asyncio.run(self.ctx.client.request_json("POST", url, expected=(list, dict), json={"symbols": symbols}))
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
            if not isinstance(data, list):
                return []
            return [row for row in data if isinstance(row, dict)]

        # Direct Binance API path (default)
        symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
        universe = [s for s in symbols if s in _PERP_SYMBOLS]
        if not universe:
            self.ctx.logger.warning("tradfi_no_supported_symbols")
            return []

        try:
            return asyncio.run(_fetch_binance(httpx.AsyncClient(), universe))
        except Exception:
            self.ctx.logger.exception("tradfi_binance_fetch_failed")
            return []

    def normalize(self, raw: list[dict[str, Any]]) -> list[Event]:
        ts = datetime.now(tz=UTC)
        out: list[Event] = []

        for row in raw:
            sym = str(row.get("symbol") or row.get("asset") or "").upper().strip()
            if not sym:
                continue

            basis_ann = row.get("basis_annualized")
            funding_ann = row.get("funding_annualized")
            meltup = row.get("meltup_score")

            direction, confidence, reason = _compute_signal(basis_ann, funding_ann, meltup)

            payload_obj = TradFiSignalPayload(
                symbol=sym,
                basis_annualized=basis_ann,
                funding_annualized=funding_ann,
                oi_change_pct=row.get("oi_change_pct"),
                meltup_score=meltup,
                direction=direction,
                confidence=confidence,
                signal_reason=reason,
            )
            payload = payload_obj.model_dump(mode="json")
            out.append(
                self.draft_event(
                    event_type=EventType.SIGNAL_TRADFI_V1,
                    payload=payload,
                    ts=ts,
                    observed_at=ts,
                    source=self.name,
                    dedupe_key=_dedupe_key(producer=self.name, symbol=sym, ts=ts),
                )
            )

        return out

    def run(self) -> ProducerResult:
        """Run with producer isolation: never raise."""

        start = time.perf_counter()
        errors: list[str] = []
        published = 0
        health: ProducerHealth = ProducerHealth.OK

        try:
            raw = self.collect()
            if not raw:
                health = ProducerHealth.DEGRADED
            events = self.normalize(raw)
            published = self.publish(events)
        except httpx.HTTPStatusError as e:
            code = getattr(e.response, "status_code", None)
            health = ProducerHealth.DEGRADED if code in (401, 403) else ProducerHealth.ERROR
            errors.append(f"HTTPStatusError: {code}")
        except Exception as e:  # noqa: BLE001
            health = ProducerHealth.ERROR
            errors.append(f"{type(e).__name__}: {e}")
            self.ctx.logger.exception("tradfi_basis_run_failed")

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
