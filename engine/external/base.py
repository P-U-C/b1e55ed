"""Base class for adapter-mediated external producers.

Provides the fetch → normalize → policy-filter → emit pipeline for
any external signal source wired via an adapter spec.
"""

from __future__ import annotations

import time
from abc import abstractmethod
from datetime import datetime
from typing import Any

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.core.events import EventType, TradFiSignalPayload
from engine.core.types import ProducerHealth, ProducerResult
from engine.external.confidence import normalize_confidence
from engine.external.connector_http import HttpConnector
from engine.external.models import ExternalObservation, RawExternalRecord
from engine.external.policy import AdapterPolicy
from engine.external.spec import AdapterSpec, load_spec
from engine.producers.base import BaseProducer

_DIRECTION_MAP: dict[str, str] = {
    "bullish": "long",
    "bearish": "short",
    "neutral": "flat",
}


class BaseExternalProducer(BaseProducer):
    """Base class for adapter-mediated external producers.

    Subclasses must define:
    - ``SPEC_PATH`` — path to the YAML adapter spec file.
    - ``normalize(raw)`` — convert a RawExternalRecord into ExternalObservations.

    The ``collect → normalize → policy-filter → emit`` pipeline is fully
    handled by ``collect()`` and ``run()``.
    """

    ADAPTER_VERSION = "1.0.0"
    INGRESS_MODE = "adapter"

    #: Subclasses override with the path to their YAML spec.
    SPEC_PATH: str = ""

    # Lazily initialised.
    _spec: AdapterSpec | None = None
    _connector: HttpConnector | None = None
    _policy: AdapterPolicy | None = None

    def _get_spec(self) -> AdapterSpec:
        if self._spec is None:
            self._spec = load_spec(self.SPEC_PATH)
        return self._spec

    def _get_connector(self) -> HttpConnector:
        if self._connector is None:
            spec = self._get_spec()
            self._connector = HttpConnector(
                base_url=spec.base_url,
                timeout_sec=spec.signals_endpoint.timeout_sec,
            )
        return self._connector

    def _get_policy(self) -> AdapterPolicy:
        if self._policy is None:
            spec = self._get_spec()
            self._policy = AdapterPolicy(
                min_confidence=spec.min_confidence,
                stale_threshold_sec=spec.stale_threshold_sec,
            )
        return self._policy

    # ------------------------------------------------------------------
    # Abstract interface for subclasses
    # ------------------------------------------------------------------

    @abstractmethod
    def normalize(self, raw: Any) -> Any:
        """Parse a RawExternalRecord into a list of ExternalObservations.

        Subclasses should accept ``RawExternalRecord`` and return
        ``list[ExternalObservation]``.  The broader ``Any`` signature
        satisfies the ``BaseProducer`` ABC requirement.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_raw(self) -> RawExternalRecord:
        """Fetch raw data from the configured signals endpoint."""
        spec = self._get_spec()
        connector = self._get_connector()
        ep = spec.signals_endpoint
        return connector.fetch(
            path=ep.path,
            method=ep.method,
            params=ep.params or None,
            headers=ep.headers or None,
            source_system=spec.name,
        )

    def emit_observation(
        self,
        obs: ExternalObservation,
        raw: RawExternalRecord,
    ) -> dict[str, Any]:
        """Emit a native b1e55ed SIGNAL_TRADFI_V1 event for an observation.

        Observations from external adapters are mapped to TradFiSignalPayload
        because they represent directional signals with confidence and horizon —
        semantically equivalent to TradFi signals.

        Returns the emitted payload dict for logging.
        """
        spec = self._get_spec()
        horizon_h = obs.horizon_hours

        # Map horizon hours to a human horizon label for the payload.
        if horizon_h <= 4:
            horizon_label = "scalp"
        elif horizon_h <= 24:
            horizon_label = "intraday"
        elif horizon_h <= 72:
            horizon_label = "swing"
        else:
            horizon_label = "position"

        direction_b1 = _DIRECTION_MAP.get(obs.direction, "flat")

        payload_obj = TradFiSignalPayload(
            symbol=obs.symbol,
            direction=direction_b1,
            confidence=normalize_confidence(obs.confidence),
            horizon=horizon_label,
            signal_reason=(f"[{self.name}] {obs.signal_type or obs.source_assertion or obs.direction}"),
            basis_annualized=None,
            funding_annualized=None,
            oi_change_pct=None,
            meltup_score=None,
        )
        payload = payload_obj.model_dump(mode="json")

        # Embed adapter metadata for traceability.
        payload["_adapter"] = {
            "source": raw.source_system,
            "endpoint": raw.source_endpoint,
            "payload_hash": raw.source_payload_hash,
            "adapter_version": self.ADAPTER_VERSION,
            "ingress_mode": self.INGRESS_MODE,
            "spec_version": spec.version,
            "domain": spec.domain,
            "regime": obs.regime,
            "hit_rate": obs.hit_rate,
            "avg_return": obs.avg_return,
            "horizon_hours": obs.horizon_hours,
            "health_state": obs.health_state,
        }

        ts = datetime.now(tz=UTC)
        dedupe_key = f"{EventType.SIGNAL_TRADFI_V1}:{self.name}:{obs.symbol}:{int(ts.timestamp())}"

        event = self.draft_event(
            event_type=EventType.SIGNAL_TRADFI_V1,
            payload=payload,
            ts=ts,
            observed_at=ts,
            source=self.name,
            dedupe_key=dedupe_key,
        )
        self.publish([event])
        payload["_event_id"] = event.id
        return payload

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def collect(self) -> list[dict]:
        """Full adapter pipeline: fetch → normalize → policy-filter → emit.

        Returns a list of payload dicts for all successfully emitted observations.
        """
        policy = self._get_policy()
        skipped = 0
        emitted: list[dict[str, Any]] = []

        try:
            raw = self._fetch_raw()
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.warning(
                "external_adapter.fetch_failed",
                extra={"producer": self.name, "error": str(exc)},
            )
            return []

        try:
            observations: list[ExternalObservation] = self.normalize(raw)
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.warning(
                "external_adapter.normalize_failed",
                extra={"producer": self.name, "error": str(exc)},
            )
            return []

        for obs in observations:
            skip, reason = policy.should_skip(obs)
            if skip:
                skipped += 1
                self.ctx.logger.debug(
                    "external_adapter.skip",
                    extra={"producer": self.name, "symbol": obs.symbol, "reason": reason},
                )
                continue

            try:
                payload = self.emit_observation(obs, raw)
                emitted.append(payload)
            except Exception as exc:  # noqa: BLE001
                self.ctx.logger.warning(
                    "external_adapter.emit_failed",
                    extra={"producer": self.name, "symbol": obs.symbol, "error": str(exc)},
                )

        self.ctx.logger.info(
            "external_adapter.collect_done",
            extra={
                "producer": self.name,
                "total": len(observations),
                "emitted": len(emitted),
                "skipped": skipped,
            },
        )
        return emitted

    def run(self) -> ProducerResult:
        """Run the producer with isolation — never raises."""
        start = time.perf_counter()
        errors: list[str] = []
        published = 0
        health: ProducerHealth = ProducerHealth.OK

        try:
            emitted = self.collect()
            published = len(emitted)
            if published == 0:
                health = ProducerHealth.DEGRADED
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            health = ProducerHealth.ERROR
            self.ctx.logger.exception("external_adapter.run_failed", extra={"producer": self.name})

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ProducerResult(
            events_published=published,
            errors=errors,
            health=health,
            duration_ms=duration_ms,
            timestamp=datetime.now(tz=UTC),
            staleness_ms=None,
        )
