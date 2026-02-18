"""engine.brain.conviction

Conviction = PCS (position conviction score) + CTS (counter-thesis score).

"Conviction without counter-thesis is just stubbornness." (Easter egg)

PCS is the weighted synthesis output.
CTS is a devil's advocate that auto-triggers when PCS is high.

This is a port/rewrite of the legacy conviction engine and counter-thesis logic,
but expressed in the v3 event + types contract.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from engine.brain.synthesis import SynthesisResult
from engine.core.config import Config
from engine.core.database import Database
from engine.core.events import EventType, canonical_json
from engine.core.types import ConvictionScore


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def _commitment_hash(payload: dict[str, Any]) -> str:
    # Commitment is over the full payload excluding commitment_hash itself.
    data = canonical_json(payload)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConvictionResult:
    score: ConvictionScore
    pcs: float
    cts: float
    final_conviction: float


class CounterThesis:
    """A tiny devil's advocate.

    This is intentionally rule-based and conservative. It exists to prevent
    high-confidence mistakes, not to find trades.
    """

    def compute(self, *, synthesis: SynthesisResult, pcs: float, regime: str) -> float:
        # Return 0..100 (higher = more counter-evidence).
        snap = synthesis.snapshot
        tech = snap.features.get("technical", {})
        tradfi = snap.features.get("tradfi", {})

        penalties: list[float] = []

        rsi = tech.get("rsi_14")
        if rsi is not None and float(rsi) >= 70.0:
            penalties.append(25.0)

        funding = tradfi.get("funding_annualized")
        if funding is not None and float(funding) >= 30.0:
            penalties.append(25.0)

        basis = tradfi.get("basis_annualized")
        if basis is not None and float(basis) >= 8.0:
            penalties.append(20.0)

        if regime == "CRISIS":
            penalties.append(30.0)

        # If PCS is high and we have any explicit contradictions, CTS ramps.
        base = sum(penalties)
        if pcs > 75.0 and base > 0:
            base += 10.0

        return float(_clamp(base, 0.0, 100.0))


class ConvictionEngine:
    def __init__(self, config: Config, db: Database, *, node_id: str):
        self.config = config
        self.db = db
        self.node_id = node_id
        self.counter_thesis = CounterThesis()

    def compute(
        self,
        *,
        synthesis: SynthesisResult,
        regime: str,
        as_of: datetime | None = None,
        timeframe: str = "4h",
    ) -> ConvictionResult:
        now = as_of or datetime.now(tz=UTC)

        # PCS is 0..100
        pcs = float(_clamp(synthesis.weighted_score * 100.0, 0.0, 100.0))
        cts = float(self.counter_thesis.compute(synthesis=synthesis, pcs=pcs, regime=regime) if pcs > 75.0 else 0.0)

        # Final conviction: penalize PCS by up to 50% (cts=100 => -50%)
        final = float(_clamp(pcs * (1.0 - cts / 200.0), 0.0, 100.0))

        # Convert into the network primitive.
        direction: str
        if final >= 55.0:
            direction = "long"
        elif final <= 45.0:
            direction = "short"
        else:
            direction = "neutral"

        magnitude = float(_clamp(abs(final - 50.0) / 5.0, 0.0, 10.0))

        payload_wo_commit = {
            "symbol": synthesis.snapshot.symbol,
            "direction": direction,
            "magnitude": magnitude,
            "timeframe": timeframe,
            "pcs_score": pcs,
            "cts_score": cts,
            "regime": regime,
            "domains_used": sorted(list(synthesis.domain_scores.keys())),
        }
        commitment = _commitment_hash(payload_wo_commit)

        score = ConvictionScore(
            node_id=self.node_id,
            symbol=synthesis.snapshot.symbol,
            direction=direction,
            magnitude=magnitude,
            timeframe=timeframe,
            ts=now,
            commitment_hash=commitment,
            pcs_score=pcs,
            cts_score=cts,
            regime=regime,
            domains_used=sorted(list(synthesis.domain_scores.keys())),
            confidence=float(_clamp((synthesis.snapshot.features and len(synthesis.snapshot.features) or 0) / 6.0, 0.0, 1.0)),
        )

        return ConvictionResult(score=score, pcs=pcs, cts=cts, final_conviction=final)

    def emit(self, result: ConvictionResult, *, cycle_id: str, source: str = "brain.conviction") -> None:
        p = {
            "symbol": result.score.symbol,
            "direction": result.score.direction,
            "magnitude": result.score.magnitude,
            "timeframe": result.score.timeframe,
            "pcs_score": result.pcs,
            "cts_score": result.cts,
            "regime": result.score.regime or "TRANSITION",
            "domains_used": list(result.score.domains_used),
            "commitment_hash": result.score.commitment_hash,
        }
        self.db.append_event(event_type=EventType.CONVICTION_V1, payload=p, source=source, trace_id=cycle_id)

        # Also persist to conviction_scores table for learning.
        with self.db.conn:
            self.db.conn.execute(
                """
                INSERT INTO conviction_scores (
                    cycle_id, node_id, symbol, direction, magnitude, timeframe, ts,
                    commitment_hash, pcs_score, cts_score, regime, domains_used, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cycle_id,
                    result.score.node_id,
                    result.score.symbol,
                    result.score.direction,
                    result.score.magnitude,
                    result.score.timeframe,
                    result.score.ts.isoformat(),
                    result.score.commitment_hash,
                    result.pcs,
                    result.cts,
                    result.score.regime,
                    canonical_json(list(result.score.domains_used)),
                    result.score.confidence,
                ),
            )
