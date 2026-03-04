"""engine.producers.polymarket

PolymarketProducer — edge estimator for Polymarket prediction contracts.

This is NOT a data feed. It estimates whether a contract is mispriced vs fair value
and emits a signal only when expected value (EV) exceeds the minimum threshold after
spread and liquidity costs.

Signal = P_true_estimate - executable_price > EV_MIN_THRESHOLD

APIs (no auth required):
  Gamma: https://gamma-api.polymarket.com  — market metadata, prices
  CLOB:  https://clob.polymarket.com       — order book depth for VWAP
"""

from __future__ import annotations

import json
import time
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from typing import Any

import httpx

from engine.core.events import EventType, payload_hash
from engine.core.models import Event
from engine.core.types import ProducerHealth, ProducerResult
from engine.producers.base import BaseProducer
from engine.producers.registry import register

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
TIMEOUT = 10
TARGET_SIZE_USD = 500.0
EV_MIN_THRESHOLD = 0.03

WATCHLIST_SLUGS = [
    "will-the-fed-cut-rates-in-march-2026",
    "will-the-fed-cut-rates-in-may-2026",
    "will-bitcoin-reach-100000-in-2026",
    "will-btc-be-above-100000-on-december-31-2026",
    "will-ethereum-reach-5000-in-2026",
]


def compute_vwap(asks: list[tuple[float, float]], target_usd: float) -> float | None:
    """Compute VWAP fill price for a BUY order of target_usd notional.

    asks: list of (price, size_usd) sorted ascending by price
    Returns None if total depth < target_usd (cannot fill).
    """

    if target_usd <= 0:
        return None

    remaining = float(target_usd)
    weighted_price = 0.0

    for price, size_usd in asks:
        if price <= 0 or size_usd <= 0:
            continue

        fill = min(size_usd, remaining)
        weighted_price += price * fill
        remaining -= fill
        if remaining <= 1e-9:
            return weighted_price / target_usd

    return None


def liquidity_tier(liquidity_usd: float) -> str:
    if liquidity_usd < 50_000:
        return "thin"
    if liquidity_usd < 500_000:
        return "low"
    return "high"


def _confidence(liquidity_usd: float, ev: float, p_true_method: str) -> float:
    liq_score = {"thin": 0.0, "low": 0.2, "high": 0.4}[liquidity_tier(liquidity_usd)]
    ev_score = min(0.3, ev * 3)
    method_score = {
        "cross_platform_discrepancy": 0.3,
        "base_rate": 0.15,
        "momentum": 0.1,
        "market_price": 0.0,
    }.get(p_true_method, 0.0)
    return round(min(1.0, liq_score + ev_score + method_score), 4)


def _dedupe_key(*, producer: str, payload: dict[str, Any]) -> str:
    return f"{EventType.SIGNAL_EVENTS_V1}:{producer}:{payload_hash(payload)}"


@register("polymarket", domain="events")
class PolymarketProducer(BaseProducer):
    schedule = "*/15 * * * *"
    mcp_source_url: str | None = None
    assets: list[str] = []

    _FED_HINTS = ("fed", "rate", "cut")
    _CRYPTO_HINTS = ("bitcoin", "btc", "ethereum", "eth")
    _CRYPTO_TARGET_HINTS = ("reach", "above", "over", "target")
    _GEOPOLITICAL_HINTS = ("war", "attack", "invasion", "missile", "nuclear", "escalat")
    _REGULATORY_HINTS = ("sec", "cftc", "regulator", "ban", "approval", "etf")

    @staticmethod
    def _to_float(value: Any, *, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _extract_markets(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                return [row for row in data if isinstance(row, dict)]
            return [payload]
        return []

    @staticmethod
    def _market_identity(market: dict[str, Any]) -> str | None:
        market_id = market.get("id")
        if market_id not in (None, ""):
            return str(market_id)

        slug = market.get("slug")
        if slug not in (None, ""):
            return str(slug)
        return None

    @staticmethod
    def _clamp_probability(value: float) -> float:
        if value < 0.0:
            return 0.0
        if value > 1.0:
            return 1.0
        return value

    @staticmethod
    def _parse_json_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed, list):
                return parsed
        return []

    @staticmethod
    def _parse_iso8601(value: str | None) -> datetime | None:
        if not value:
            return None
        norm = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            dt = datetime.fromisoformat(norm)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    def _append_unique_market(self, out: list[dict[str, Any]], seen: set[str], market: dict[str, Any]) -> None:
        ident = self._market_identity(market)
        if ident is None or ident in seen:
            return
        seen.add(ident)
        out.append(market)

    def collect(self) -> list[dict[str, Any]]:
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                out: list[dict[str, Any]] = []
                seen: set[str] = set()

                for slug in WATCHLIST_SLUGS:
                    response = client.get(f"{GAMMA_BASE}/markets", params={"slug": slug, "active": "true"})
                    response.raise_for_status()
                    for market in self._extract_markets(response.json()):
                        self._append_unique_market(out, seen, market)

                newest_response = client.get(
                    f"{GAMMA_BASE}/markets",
                    params={
                        "tag": "crypto",
                        "sort": "newest",
                        "limit": 20,
                        "active": "true",
                        "closed": "false",
                    },
                )
                newest_response.raise_for_status()

                for market in self._extract_markets(newest_response.json()):
                    liquidity = self._to_float(market.get("liquidity") or market.get("liquidityClob"))
                    if liquidity < 50_000 or bool(market.get("new")):
                        self._append_unique_market(out, seen, market)

                return out
        except httpx.HTTPError as exc:
            self.ctx.logger.warning("polymarket_collect_http_error", extra={"error": str(exc)})
            return []

    def _text_blob(self, market: dict[str, Any]) -> str:
        slug = str(market.get("slug") or "")
        question = str(market.get("question") or "")
        title = str(market.get("title") or "")
        return f"{slug} {question} {title}".lower()

    def _is_fed_market(self, text: str) -> bool:
        return all(h in text for h in self._FED_HINTS)

    def _is_crypto_target_market(self, text: str) -> bool:
        has_asset = any(h in text for h in self._CRYPTO_HINTS)
        has_target = any(h in text for h in self._CRYPTO_TARGET_HINTS)
        return has_asset and has_target

    def _is_geopolitical_market(self, text: str) -> bool:
        return any(h in text for h in self._GEOPOLITICAL_HINTS)

    def _category_from_market(self, market: dict[str, Any]) -> str:
        text = self._text_blob(market)

        if self._is_fed_market(text):
            return "macro"
        if self._is_crypto_target_market(text):
            return "crypto"
        if self._is_geopolitical_market(text):
            return "geopolitical"
        if any(h in text for h in self._REGULATORY_HINTS):
            return "regulatory"
        return "other"

    def _derive_signal(self, market: dict[str, Any], probability: float, probability_delta_24h: float) -> str:
        text = self._text_blob(market)

        if self._is_fed_market(text):
            if probability > 0.5 and probability_delta_24h > 0:
                return "risk_on"
            if probability < 0.3:
                return "risk_off"
            return "neutral"

        if self._is_crypto_target_market(text):
            if probability > 0.5:
                return "risk_on"
            if probability < 0.2:
                return "risk_off"
            return "neutral"

        if self._is_geopolitical_market(text) and probability > 0.5:
            return "risk_off"

        return "neutral"

    def _resolves_at(self, market: dict[str, Any]) -> str | None:
        end_date = market.get("endDate") or market.get("resolutionDate")
        if end_date:
            return str(end_date)

        events = market.get("events")
        if isinstance(events, list) and events and isinstance(events[0], dict):
            event_end = events[0].get("endDate") or events[0].get("resolutionDate")
            if event_end:
                return str(event_end)

        return None

    def _extract_probability(self, market: dict[str, Any]) -> float:
        prices = self._parse_json_list(market.get("outcomePrices"))
        if prices:
            return self._clamp_probability(self._to_float(prices[0]))

        last_trade = market.get("lastTradePrice")
        if last_trade not in (None, ""):
            return self._clamp_probability(self._to_float(last_trade))

        best_ask = market.get("bestAsk")
        if best_ask not in (None, ""):
            return self._clamp_probability(self._to_float(best_ask))

        return 0.0

    def _estimate_p_true(self, *, mid_price: float, probability_delta_24h: float) -> tuple[float, str]:
        if abs(probability_delta_24h) >= 0.08:
            shifted = self._clamp_probability(mid_price + (0.5 * probability_delta_24h))
            return shifted, "momentum"

        return self._clamp_probability(mid_price), "market_price"

    def _primary_token_id(self, market: dict[str, Any]) -> str | None:
        token_ids = self._parse_json_list(market.get("clobTokenIds"))
        if token_ids:
            token = token_ids[0]
            if token not in (None, ""):
                return str(token)
        return None

    def _book_asks(self, book_payload: dict[str, Any]) -> list[tuple[float, float]]:
        raw_asks = book_payload.get("asks")
        if not isinstance(raw_asks, list):
            return []

        asks: list[tuple[float, float]] = []
        for level in raw_asks:
            if not isinstance(level, dict):
                continue

            price = self._to_float(level.get("price"), default=0.0)
            size = self._to_float(level.get("size"), default=0.0)
            if price <= 0 or size <= 0:
                continue

            size_usd = price * size
            asks.append((price, size_usd))

        asks.sort(key=lambda row: row[0])
        return asks

    def _executable_price(
        self,
        market: dict[str, Any],
        *,
        best_ask: float,
        client: httpx.Client,
    ) -> tuple[float, str]:
        ask_fallback = self._clamp_probability(best_ask)
        token_id = self._primary_token_id(market)
        if token_id is None:
            return ask_fallback, "CLOB unavailable (missing token id); used best ask"

        try:
            response = client.get(f"{CLOB_BASE}/book", params={"token_id": token_id})
            response.raise_for_status()
            book = response.json()
            if not isinstance(book, dict):
                return ask_fallback, "CLOB unavailable (invalid order book payload); used best ask"

            asks = self._book_asks(book)
            vwap = compute_vwap(asks, TARGET_SIZE_USD)
            if vwap is None:
                return ask_fallback, "CLOB depth insufficient for target size; used best ask"
            return self._clamp_probability(vwap), "CLOB VWAP"
        except httpx.HTTPError as exc:
            contract = self._market_identity(market)
            self.ctx.logger.warning(
                "polymarket_clob_unavailable",
                extra={"contract": contract, "token_id": token_id, "error": str(exc)},
            )
            return ask_fallback, "CLOB unavailable; used best ask"

    def _normalize_market(self, market: dict[str, Any], *, client: httpx.Client, ts: datetime) -> Event | None:
        contract = str(market.get("slug") or market.get("id") or "").strip()
        if not contract:
            return None

        probability = self._extract_probability(market)

        best_bid = self._to_float(market.get("bestBid"), default=probability)
        best_ask = self._to_float(market.get("bestAsk"), default=probability)
        best_bid = self._clamp_probability(best_bid)
        best_ask = self._clamp_probability(best_ask)

        mid_price = self._clamp_probability((best_bid + best_ask) / 2.0)
        probability_delta_24h = self._to_float(
            market.get("oneDayPriceChange") if market.get("oneDayPriceChange") is not None else market.get("probability_delta_24h"),
            default=0.0,
        )

        p_true_estimate, p_true_method = self._estimate_p_true(mid_price=mid_price, probability_delta_24h=probability_delta_24h)
        executable_price, executable_note = self._executable_price(market, best_ask=best_ask, client=client)

        ev = p_true_estimate - executable_price
        if ev < EV_MIN_THRESHOLD:
            return None

        ev_return_rate = ev / executable_price if executable_price > 0 else 0.0
        spread_cost = executable_price - mid_price

        liquidity_usd = self._to_float(market.get("liquidity") or market.get("liquidityClob"), default=0.0)
        volume_24h_usd = self._to_float(market.get("volume24hr") or market.get("volume24hrClob"), default=0.0)

        signal = self._derive_signal(market, probability, probability_delta_24h)
        resolves_at = self._resolves_at(market)
        category = self._category_from_market(market)

        reason = (
            f"{p_true_method} heuristic: p_true={p_true_estimate:.4f}, exec={executable_price:.4f}, "
            f"ev={ev:.4f}, delta24h={probability_delta_24h:.4f}. {executable_note}"
        )

        payload = {
            "contract": contract,
            "category": category,
            "liquidity_tier": liquidity_tier(liquidity_usd),
            "mid_price": mid_price,
            "executable_price": executable_price,
            "p_true_estimate": p_true_estimate,
            "p_true_method": p_true_method,
            "ev": ev,
            "ev_return_rate": ev_return_rate,
            "spread_cost": spread_cost,
            "probability": probability,
            "probability_delta_24h": probability_delta_24h,
            "volume_24h_usd": volume_24h_usd,
            "liquidity_usd": liquidity_usd,
            "resolves_at": resolves_at,
            "signal": signal,
            "confidence": _confidence(liquidity_usd, ev, p_true_method),
            "reason": reason,
            "direction": signal,
        }

        return self.draft_event(
            event_type=EventType.SIGNAL_EVENTS_V1,
            payload=payload,
            ts=ts,
            observed_at=ts,
            source=self.name,
            dedupe_key=_dedupe_key(producer=self.name, payload=payload),
        )

    def normalize(self, raw: list[dict[str, Any]]) -> list[Event]:
        if not raw:
            return []

        ts = datetime.now(tz=UTC)
        out: list[Event] = []

        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                for market in raw:
                    if not isinstance(market, dict):
                        continue

                    event = self._normalize_market(market, client=client, ts=ts)
                    if event is not None:
                        out.append(event)
        except httpx.HTTPError as exc:
            self.ctx.logger.warning("polymarket_normalize_http_error", extra={"error": str(exc)})
            return []

        return out

    def _fetch_market_by_contract(self, *, client: httpx.Client, contract: str) -> dict[str, Any] | None:
        for params in ({"slug": contract}, {"id": contract}):
            response = client.get(f"{GAMMA_BASE}/markets", params=params)
            response.raise_for_status()
            markets = self._extract_markets(response.json())
            if markets:
                return markets[0]
        return None

    def _resolution_candidates(self) -> dict[str, dict[str, Any]]:
        now = datetime.now(tz=UTC)

        history = self.ctx.db.get_events(event_type=EventType.SIGNAL_EVENTS_V1, source=self.name, limit=5_000)

        pending: dict[str, dict[str, Any]] = {}
        settled_contracts: set[str] = set()

        for event in history:
            payload = event.payload if isinstance(event.payload, dict) else {}
            contract = str(payload.get("contract") or "").strip()
            if not contract:
                continue

            if payload.get("subtype") == "polymarket_resolution":
                settled_contracts.add(contract)
                continue

            resolves_at_raw = payload.get("resolves_at")
            resolves_at = self._parse_iso8601(str(resolves_at_raw)) if isinstance(resolves_at_raw, str) else None
            if resolves_at is None or resolves_at > now:
                continue

            if contract not in pending:
                pending[contract] = payload

        for contract in settled_contracts:
            pending.pop(contract, None)

        return pending

    def _extract_resolution_outcome(self, market: dict[str, Any]) -> str:
        winner = market.get("winner")
        if winner not in (None, ""):
            return str(winner)

        outcomes = [str(x) for x in self._parse_json_list(market.get("outcomes")) if x not in (None, "")]
        prices = [self._to_float(x, default=0.0) for x in self._parse_json_list(market.get("outcomePrices"))]

        if outcomes and prices and len(outcomes) == len(prices):
            max_idx = max(range(len(prices)), key=prices.__getitem__)
            return outcomes[max_idx]

        return "unknown"

    def _resolution_events(self) -> list[Event]:
        pending = self._resolution_candidates()
        if not pending:
            return []

        ts = datetime.now(tz=UTC)
        out: list[Event] = []

        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                for contract, base_payload in pending.items():
                    market = self._fetch_market_by_contract(client=client, contract=contract)
                    if market is None:
                        continue

                    if market.get("isResolved") is not True:
                        continue

                    outcome = self._extract_resolution_outcome(market)
                    resolved_at = str(market.get("resolutionDate") or market.get("endDate") or ts.isoformat())

                    payload = {
                        "subtype": "polymarket_resolution",
                        "contract": contract,
                        "outcome": outcome,
                        "resolves_at": base_payload.get("resolves_at"),
                        "resolved_at": resolved_at,
                        "reason": f"Polymarket market resolved with outcome={outcome}",
                    }

                    out.append(
                        self.draft_event(
                            event_type=EventType.SIGNAL_EVENTS_V1,
                            payload=payload,
                            ts=ts,
                            observed_at=ts,
                            source=self.name,
                            dedupe_key=f"{EventType.SIGNAL_EVENTS_V1}:{self.name}:resolution:{contract}:{outcome}",
                        )
                    )
        except httpx.HTTPError as exc:
            self.ctx.logger.warning("polymarket_resolution_http_error", extra={"error": str(exc)})
            return []

        return out

    def run(self) -> ProducerResult:
        start = time.perf_counter()
        errors: list[str] = []
        published = 0
        health: ProducerHealth = ProducerHealth.OK

        try:
            raw = self.collect()
            signal_events = self.normalize(raw)
            published += self.publish(signal_events)

            resolution_events = self._resolution_events()
            if resolution_events:
                published += self.publish(resolution_events)
        except Exception as exc:  # noqa: BLE001
            health = ProducerHealth.ERROR
            errors.append(f"{type(exc).__name__}: {exc}")
            self.ctx.logger.exception("polymarket_run_failed")

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
            health=health,
        )
