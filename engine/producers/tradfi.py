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
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017
from typing import Any

import httpx

from engine.core.events import (
    AbstentionReason,
    EventType,
    ForecastLifecycleState,
    ForecastPayload,
    TradFiSignalPayload,
)
from engine.core.forecast import abstain, compute_reasoning_hash, make_forecast_id
from engine.core.interpreter import Interpreter, NullInterpreter
from engine.core.models import Event
from engine.core.regime import RegimeConfig, RegimeMatrix
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


async def _fetch_hl_liquidations(client: httpx.AsyncClient, symbols: list[str]) -> dict[str, dict[str, float]]:
    """Fetch Hyperliquid liquidation-cluster proxy data.

    Returns:
        dict[symbol -> {liquidation_cluster_long, liquidation_cluster_short, liq_asymmetry}]

    Fails silently and returns {} on any error.
    """

    try:
        resp = await client.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "metaAndAssetCtxs"},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list) or len(data) < 2:
            return {}

        meta = data[0] if isinstance(data[0], dict) else {}
        asset_ctxs = data[1] if isinstance(data[1], list) else []
        universe = meta.get("universe", []) if isinstance(meta, dict) else []

        symbol_set = {s.upper() for s in symbols}
        result: dict[str, dict[str, float]] = {}

        for idx, asset_info in enumerate(universe):
            if not isinstance(asset_info, dict):
                continue
            name = str(asset_info.get("name", "")).upper()
            if name not in symbol_set or idx >= len(asset_ctxs):
                continue

            ctx = asset_ctxs[idx] if isinstance(asset_ctxs[idx], dict) else {}
            mark_px = float(ctx.get("markPx", 0) or 0)
            oi = float(ctx.get("openInterest", 0) or 0)
            funding = float(ctx.get("funding", 0) or 0)

            # Heuristic split: positive funding implies longer crowding.
            crowding_bias = max(-0.4, min(0.4, funding * 100))
            long_frac = max(0.1, min(0.9, 0.5 + crowding_bias))
            short_frac = 1.0 - long_frac

            long_cluster = oi * mark_px * long_frac * 0.15
            short_cluster = oi * mark_px * short_frac * 0.15
            total = long_cluster + short_cluster
            liq_asymmetry = long_cluster / total if total > 0 else 0.5

            result[name] = {
                "liquidation_cluster_long": round(long_cluster, 0),
                "liquidation_cluster_short": round(short_cluster, 0),
                "liq_asymmetry": round(liq_asymmetry, 3),
            }

        return result
    except Exception:  # noqa: BLE001
        return {}


async def _fetch_nansen_smart_money(
    client: httpx.AsyncClient,
    symbols: list[str],
    *,
    api_key: str | None,
) -> dict[str, float]:
    """Best-effort smart-money netflow fetch.

    Env-gated by NANSEN_API_KEY. Returns {} on any error.
    """

    if not api_key:
        return {}

    try:
        resp = await client.post(
            "https://api.nansen.ai/api/v1/smart-money/netflow",
            headers={
                "apiKey": api_key,
                "User-Agent": "b1e55ed-tradfi-producer/1.0",
            },
            json={"symbols": symbols},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()

        rows: Any
        if isinstance(data, dict):
            rows = data.get("data", data.get("results", []))
        else:
            rows = data

        if not isinstance(rows, list):
            return {}

        result: dict[str, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or row.get("asset") or "").upper().strip()
            if not sym:
                continue

            val = row.get("netflow_usd")
            if val is None:
                val = row.get("netflow")
            if val is None:
                val = row.get("smart_money_delta")
            if val is None:
                continue

            try:
                result[sym] = float(val)
            except (TypeError, ValueError):
                continue

        return result
    except Exception:  # noqa: BLE001
        return {}


async def _collect_direct(universe: list[str]) -> list[dict[str, Any]]:
    """Collect TradFi basis rows and enrich with optional differentiated inputs."""

    async with httpx.AsyncClient() as client:
        base_rows = await _fetch_binance(client, universe)
        liq_by_symbol = await _fetch_hl_liquidations(client, universe)
        smart_money = await _fetch_nansen_smart_money(
            client,
            universe,
            api_key=os.getenv("NANSEN_API_KEY"),
        )

    for row in base_rows:
        sym = str(row.get("symbol", "")).upper().strip()
        if not sym:
            continue

        row.update(liq_by_symbol.get(sym, {}))
        row["smart_money_delta"] = smart_money.get(sym)

    return base_rows


def _dedupe_key(*, producer: str, symbol: str, ts: datetime) -> str:
    """Symbol + timestamp (+ producer) dedupe key."""
    return f"{EventType.SIGNAL_TRADFI_V1}:{producer}:{symbol}:{int(ts.timestamp())}"


# The basis -- spot minus futures -- is the oldest arbitrage signal in financial markets.
# Cash-and-carry predates electronic trading. What changed is who is on the other side.
class TradFiBasisInterpreter(Interpreter):
    """Rule-based interpreter for TradFi basis/carry signals → FORECAST_V1."""

    regime_matrix = RegimeMatrix(
        configs={
            # Bull: basis trade works well, slight confidence boost.
            "BULL": RegimeConfig(confidence_multiplier=1.1),
            # Bear: basis signals less reliable, require higher conviction.
            "BEAR": RegimeConfig(confidence_multiplier=0.8, min_confidence=0.45),
            # Crisis: basis unwinds chaotically — do not trade.
            "CRISIS": RegimeConfig(abstain=True),
            # Transition: moderate suppression.
            "TRANSITION": RegimeConfig(confidence_multiplier=0.9),
        }
    )

    def interpret(
        self,
        *,
        asset: str,
        horizon: str,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
        visible_signal_refs: list[str] | None = None,
    ) -> ForecastPayload:
        asset_signals = [s for s in signals if str(s.get("symbol", "")).upper() == asset.upper()]

        if not asset_signals:
            return abstain(
                source=self.source,
                asset=asset,
                horizon=horizon,
                reason=AbstentionReason.INSUFFICIENT_DATA,
                regime_tag=regime_tag,
                visible_signal_refs=visible_signal_refs or [],
            )

        sig = asset_signals[0]
        direction = sig.get("direction", "flat")
        raw_confidence = float(sig.get("confidence", 0.0))

        if direction == "long" and raw_confidence >= 0.3:
            action = "long"
        elif direction == "short" and raw_confidence >= 0.3:
            action = "short"
        else:
            action = "flat"

        # P3.3: differentiated confidence adjustments
        liq_asym = float(sig.get("liq_asymmetry") or 0.5)
        smart_delta: float | None
        try:
            smart_delta = float(sig.get("smart_money_delta")) if sig.get("smart_money_delta") is not None else None
        except (TypeError, ValueError):
            smart_delta = None

        if action == "long" and liq_asym > 0.65:
            raw_confidence *= 0.85
        if action == "long" and smart_delta is not None and smart_delta > 0:
            raw_confidence = min(raw_confidence * 1.1, 0.95)
        if action == "long" and smart_delta is not None and smart_delta < -1_000_000:
            raw_confidence *= 0.75

        if raw_confidence < 0.3 or action == "flat":
            return abstain(
                source=self.source,
                asset=asset,
                horizon=horizon,
                reason=AbstentionReason.INSUFFICIENT_DATA,
                regime_tag=regime_tag,
                visible_signal_refs=visible_signal_refs or [],
            )

        reasoning_hash = compute_reasoning_hash(
            candidate={"action": action, "confidence": raw_confidence, "asset": asset},
            critique="",
            rationale=sig.get("signal_reason", ""),
        )

        return ForecastPayload(
            forecast_id=make_forecast_id(),
            asset=asset,
            horizon=horizon,
            action=action,
            confidence=raw_confidence,
            calibrated=False,
            source=self.source,
            regime_tag=regime_tag,
            lifecycle_state=ForecastLifecycleState.NEW,
            reasoning_hash=reasoning_hash,
            visible_signal_refs=visible_signal_refs or [],
            used_signal_refs=[r for r in (visible_signal_refs or []) if r],
        )


@register("tradfi-basis", domain="tradfi")
class TradFiBasisProducer(BaseProducer):
    """Produce basis/carry signals for the configured universe."""

    schedule = "*/30 * * * *"
    mcp_source_url: str | None = None  # override with MCP server URL when available
    interpreter: Interpreter | NullInterpreter | None = TradFiBasisInterpreter()

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
            return asyncio.run(_collect_direct(universe))
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
                smart_money_delta=row.get("smart_money_delta"),
                liquidation_cluster_long=row.get("liquidation_cluster_long"),
                liquidation_cluster_short=row.get("liquidation_cluster_short"),
                liq_asymmetry=row.get("liq_asymmetry"),
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
            normalized_events = self.normalize(raw)
            published = self.publish(normalized_events)

            symbols = [s.upper().strip() for s in self.ctx.config.universe.symbols]
            for symbol in symbols:
                self.emit_forecast(
                    asset=symbol,
                    horizon="4h",
                    signals=[e.payload for e in normalized_events],
                    regime_tag="unknown",
                    visible_signal_refs=[],
                )
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
