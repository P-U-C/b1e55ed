from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest

from engine.core.client import DataClient
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import AbstentionReason, EventType, ForecastLifecycleState, ForecastPayload
from engine.core.forecast import abstain, make_forecast_id
from engine.core.horizons import DEFAULT_HORIZONS, HorizonConfig, apply_horizon_config
from engine.core.interpreter import Interpreter
from engine.core.metrics import MetricsRegistry
from engine.producers.base import BaseProducer, ProducerContext
from engine.producers.tradfi import TradFiBasisProducer


class _DummyClient:
    def __init__(self, response: httpx.Response | None = None, exc: Exception | None = None):
        self._response = response
        self._exc = exc

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response

    async def request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        resp = await self.request(method, url, **kwargs)
        return resp.json()


class _FixedInterpreter(Interpreter):
    def __init__(self, *, action: str = "long", confidence: float = 0.7) -> None:
        self._action = action
        self._confidence = confidence

    def interpret(
        self,
        *,
        asset: str,
        horizon: str,
        signals: list[dict[str, Any]],
        regime_tag: str = "unknown",
        visible_signal_refs: list[str] | None = None,
    ) -> ForecastPayload:
        refs = visible_signal_refs or []
        if self._action == "no_forecast":
            return abstain(
                source=self.source,
                asset=asset,
                horizon=horizon,
                reason=AbstentionReason.INSUFFICIENT_DATA,
                regime_tag=regime_tag,
                visible_signal_refs=refs,
            )

        return ForecastPayload(
            forecast_id=make_forecast_id(),
            asset=asset,
            horizon=horizon,
            action=self._action,
            confidence=self._confidence,
            source=self.source,
            regime_tag=regime_tag,
            lifecycle_state=ForecastLifecycleState.NEW,
            visible_signal_refs=refs,
            used_signal_refs=refs,
        )


class _TestProducer(BaseProducer):
    name = "multi-horizon-test"
    domain = "events"
    schedule = "continuous"

    def collect(self) -> list[dict]:
        return []

    def normalize(self, raw: list[dict]):  # type: ignore[no-untyped-def]
        return []


def _make_ctx(tmp_path) -> ProducerContext:
    db = Database(tmp_path / "events.db")
    return ProducerContext(
        config=Config(),
        db=db,
        client=DataClient(),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )


def test_apply_horizon_config_under_cap() -> None:
    cfg = HorizonConfig("4h", confidence_scale=1.0, confidence_cap=0.85)
    assert apply_horizon_config(0.80, cfg) == pytest.approx(0.80)


def test_apply_horizon_config_capped() -> None:
    cfg = HorizonConfig("4h", confidence_scale=1.0, confidence_cap=0.85)
    assert apply_horizon_config(0.90, cfg) == pytest.approx(0.85)


def test_apply_horizon_config_scaled_and_capped() -> None:
    cfg = HorizonConfig("3d", confidence_scale=1.10, confidence_cap=0.88)
    assert apply_horizon_config(0.80, cfg) == pytest.approx(0.88)


def test_emit_forecasts_multi_horizon_publishes_for_each_enabled_horizon(tmp_path) -> None:
    producer = _TestProducer(_make_ctx(tmp_path))
    producer.interpreter = _FixedInterpreter(action="long", confidence=0.7)

    configs = [
        HorizonConfig("4h", confidence_scale=1.0, confidence_cap=0.85),
        HorizonConfig("24h", confidence_scale=1.0, confidence_cap=0.85),
        HorizonConfig("3d", confidence_scale=1.0, confidence_cap=0.85),
    ]

    published = producer.emit_forecasts_multi_horizon(
        asset="BTC",
        signals=[{"symbol": "BTC"}],
        regime_tag="unknown",
        visible_signal_refs=["evt-1"],
        horizon_configs=configs,
    )

    events = producer.ctx.db.get_events(event_type=EventType.FORECAST_V1, source=producer.name, limit=10)

    assert published == 3
    assert len(events) == 3
    assert {event.payload["horizon"] for event in events} == {"4h", "24h", "3d"}


def test_emit_forecasts_multi_horizon_skips_no_forecast(tmp_path) -> None:
    producer = _TestProducer(_make_ctx(tmp_path))
    producer.interpreter = _FixedInterpreter(action="no_forecast", confidence=0.7)

    published = producer.emit_forecasts_multi_horizon(
        asset="BTC",
        signals=[{"symbol": "BTC"}],
        horizon_configs=[HorizonConfig("4h", confidence_scale=1.0, confidence_cap=0.85)],
    )

    events = producer.ctx.db.get_events(event_type=EventType.FORECAST_V1, source=producer.name, limit=10)

    assert published == 0
    assert events == []


def test_emit_forecasts_multi_horizon_skips_low_scaled_confidence(tmp_path) -> None:
    producer = _TestProducer(_make_ctx(tmp_path))
    producer.interpreter = _FixedInterpreter(action="long", confidence=0.12)

    published = producer.emit_forecasts_multi_horizon(
        asset="BTC",
        signals=[{"symbol": "BTC"}],
        horizon_configs=[HorizonConfig("4h", confidence_scale=0.5, confidence_cap=0.85)],
    )

    events = producer.ctx.db.get_events(event_type=EventType.FORECAST_V1, source=producer.name, limit=10)

    assert published == 0
    assert events == []


def test_emit_forecasts_multi_horizon_uses_default_configs(tmp_path) -> None:
    producer = _TestProducer(_make_ctx(tmp_path))
    producer.interpreter = _FixedInterpreter(action="long", confidence=0.7)

    published = producer.emit_forecasts_multi_horizon(
        asset="BTC",
        signals=[{"symbol": "BTC"}],
    )

    events = producer.ctx.db.get_events(event_type=EventType.FORECAST_V1, source=producer.name, limit=10)

    assert published == 1
    assert len(events) == 1
    assert events[0].payload["horizon"] == DEFAULT_HORIZONS[0].label


def test_tradfi_run_emits_three_horizons_per_symbol(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("B1E55ED_TRADFI_BASIS_URL", "https://example.test/basis")

    resp = httpx.Response(
        200,
        json={
            "data": [
                {
                    "symbol": "BTC",
                    "basis_annualized": 4.0,
                    "funding_annualized": 10.0,
                    "oi_change_pct": 1.5,
                    "meltup_score": 2.0,
                }
            ]
        },
        request=httpx.Request("POST", "https://example.test/basis"),
    )

    db = Database(tmp_path / "events.db")
    cfg = Config(universe={"symbols": ["BTC"]})
    ctx = ProducerContext(
        config=cfg,
        db=db,
        client=_DummyClient(response=resp),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )

    TradFiBasisProducer(ctx).run()

    forecast_events = db.get_events(event_type=EventType.FORECAST_V1, source="tradfi-basis", limit=10)

    assert len(forecast_events) == 3
    assert {event.payload["horizon"] for event in forecast_events} == {"4h", "24h", "3d"}

    confidence_by_horizon = {event.payload["horizon"]: event.payload["confidence"] for event in forecast_events}
    assert confidence_by_horizon["4h"] == pytest.approx(0.55)
    assert confidence_by_horizon["24h"] == pytest.approx(0.5775)
    assert confidence_by_horizon["3d"] == pytest.approx(0.5225)
