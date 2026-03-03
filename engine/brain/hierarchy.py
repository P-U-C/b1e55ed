"""engine.brain.hierarchy

Hierarchical weight computation for P4.1.

Computes per-domain weight multipliers from:
  - producer_reliability: trailing Brier score (regime-aware)
  - asset_fit: per-asset per-domain historical performance
  - regime_fit: domain performance in current regime
  - correlation_penalty: from P2.3 correlation data

freshness_factor already applied in build_snapshot() — not here.

All multipliers return 1.0 (neutral) when data is insufficient,
ensuring graceful degradation when tables are empty or P2.x data
is unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Guardrail constants
MIN_BRIER_SAMPLES = 5  # minimum resolved forecasts before reliability applies
MIN_ASSET_SAMPLES = 3  # minimum per-asset samples before asset_fit applies
RELIABILITY_WEIGHT = 0.40  # weight of producer reliability in final multiplier
ASSET_FIT_WEIGHT = 0.25  # weight of asset fit
REGIME_FIT_WEIGHT = 0.25  # weight of regime fit
CORRELATION_WEIGHT = 0.10  # weight of correlation penalty
MAX_MULTIPLIER = 2.0  # cap: a domain can at most double its prior weight
MIN_MULTIPLIER = 0.1  # floor: a domain can at most lose 90% of its prior weight


@dataclass
class HierarchyFactors:
    """Per-domain weight factors computed for one cycle."""

    domain: str
    producer_reliability: float = 1.0
    asset_fit: float = 1.0
    regime_fit: float = 1.0
    correlation_penalty: float = 0.0
    final_multiplier: float = 1.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class HierarchyResult:
    """Result of a hierarchy computation cycle."""

    multipliers: dict[str, float]
    factors: dict[str, HierarchyFactors]
    regime: str = "unknown"


class HierarchyEngine:
    """Computes hierarchical weight multipliers per domain per cycle."""

    def __init__(self, db: Any):
        self.db = db

    @property
    def _conn(self) -> Any:
        return getattr(self.db, "conn", self.db)

    def compute(
        self,
        *,
        symbol: str,
        regime: str = "unknown",
        producer_domain_map: dict[str, str],
    ) -> HierarchyResult:
        """Compute per-domain multipliers for this cycle."""
        regime_norm = str(regime or "unknown").upper()
        domains = {str(d) for d in producer_domain_map.values() if str(d)}
        factors: dict[str, HierarchyFactors] = {}

        for domain in domains:
            domain_producers = [p for p, d in producer_domain_map.items() if d == domain]
            f = HierarchyFactors(domain=domain)

            # 1) producer reliability (trailing Brier, regime-aware)
            f.producer_reliability = self._producer_reliability(domain_producers, regime=regime_norm)
            if f.producer_reliability != 1.0:
                f.reasons.append(f"reliability={f.producer_reliability:.3f}")

            # 2) asset fit
            f.asset_fit = self._asset_fit(domain_producers, symbol=symbol)
            if f.asset_fit != 1.0:
                f.reasons.append(f"asset_fit={f.asset_fit:.3f}")

            # 3) regime fit
            f.regime_fit = self._regime_fit(domain_producers, regime=regime_norm)
            if f.regime_fit != 1.0:
                f.reasons.append(f"regime_fit={f.regime_fit:.3f}")

            # 4) correlation penalty
            f.correlation_penalty = self._correlation_penalty(
                domain=domain,
                producer_domain_map=producer_domain_map,
                symbol=symbol,
                regime=regime_norm,
            )
            if f.correlation_penalty > 0.05:
                f.reasons.append(f"corr_penalty={f.correlation_penalty:.3f}")

            # Weighted blend of hierarchy factors.
            raw = (
                RELIABILITY_WEIGHT * f.producer_reliability
                + ASSET_FIT_WEIGHT * f.asset_fit
                + REGIME_FIT_WEIGHT * f.regime_fit
                + CORRELATION_WEIGHT * (1.0 - f.correlation_penalty)
            ) / (RELIABILITY_WEIGHT + ASSET_FIT_WEIGHT + REGIME_FIT_WEIGHT + CORRELATION_WEIGHT)

            f.final_multiplier = _clamp(raw, MIN_MULTIPLIER, MAX_MULTIPLIER)
            factors[domain] = f

        multipliers = {d: f.final_multiplier for d, f in factors.items()}
        logger.debug(
            "hierarchy computed symbol=%s regime=%s multipliers=%s",
            symbol,
            regime_norm,
            multipliers,
        )

        return HierarchyResult(
            multipliers=multipliers,
            factors=factors,
            regime=regime_norm,
        )

    def _producer_reliability(self, producers: list[str], regime: str) -> float:
        """Brier-based reliability score for producer set -> multiplier."""
        if not producers:
            return 1.0

        from engine.brain.calibration import brier_summary

        scores: list[float] = []
        regime_norm = str(regime or "unknown").upper()

        for producer in producers:
            try:
                summary = brier_summary(self.db, producer, window_days=30)
            except Exception:
                continue

            count = int(summary.get("count") or 0)
            if count < MIN_BRIER_SAMPLES:
                continue

            mean_brier = float(summary.get("mean_brier") or 0.25)
            breakdown_raw = summary.get("regime_breakdown") or {}
            breakdown = {str(k).upper(): v for k, v in breakdown_raw.items() if isinstance(v, dict)}
            regime_data = breakdown.get(regime_norm)
            if regime_data and int(regime_data.get("count") or 0) >= 3:
                regime_brier = float(regime_data.get("mean_brier") or mean_brier)
                mean_brier = (0.7 * mean_brier) + (0.3 * regime_brier)

            scores.append(_brier_to_multiplier(mean_brier))

        if not scores:
            return 1.0

        return _clamp(sum(scores) / len(scores), 0.5, 1.5)

    def _asset_fit(self, producers: list[str], symbol: str) -> float:
        """Per-asset historical Brier performance for this producer set."""
        symbol_norm = str(symbol or "").upper()
        if not producers or not symbol_norm:
            return 1.0

        try:
            row = self._query_brier_mean(
                producers,
                extra_where="""
                    AND UPPER(asset) = ?
                    AND datetime(resolved_at) >= datetime('now', '-60 days')
                """,
                extra_params=(symbol_norm,),
            )
            if row is None:
                return 1.0
            count, mean_brier = row
            if count < MIN_ASSET_SAMPLES:
                return 1.0
            return _clamp(_brier_to_multiplier(mean_brier), 0.5, 1.5)
        except Exception:
            return 1.0

    def _regime_fit(self, producers: list[str], regime: str) -> float:
        """Historical Brier performance in the active regime for this producer set."""
        regime_norm = str(regime or "unknown").upper()
        if not producers or regime_norm in {"UNKNOWN", "TRANSITION"}:
            return 1.0

        try:
            row = self._query_brier_mean(
                producers,
                extra_where="AND UPPER(regime) = ?",
                extra_params=(regime_norm,),
            )
            if row is None:
                return 1.0
            count, mean_brier = row
            if count < MIN_BRIER_SAMPLES:
                return 1.0
            return _clamp(_brier_to_multiplier(mean_brier), 0.5, 1.5)
        except Exception:
            return 1.0

    def _query_brier_mean(
        self,
        producers: list[str],
        *,
        extra_where: str = "",
        extra_params: tuple[Any, ...] = (),
    ) -> tuple[int, float] | None:
        if not producers:
            return None

        placeholders = ",".join("?" for _ in producers)
        query = f"""
            SELECT COUNT(*), AVG(brier_score)
            FROM forecast_calibration
            WHERE producer_name IN ({placeholders})
              AND resolved_at IS NOT NULL
              {extra_where}
        """
        params = tuple(producers) + tuple(extra_params)
        row = self._conn.execute(query, params).fetchone()
        if row is None:
            return None

        count = int(row[0] or 0)
        mean_brier = float(row[1] or 0.25)
        return count, mean_brier

    def _correlation_penalty(
        self,
        *,
        domain: str,
        producer_domain_map: dict[str, str],
        symbol: str,
        regime: str,
    ) -> float:
        """Domain-level penalty derived from producer_correlation pair data."""
        domain_producers = [p for p, d in producer_domain_map.items() if d == domain]
        other_producers = [p for p, d in producer_domain_map.items() if d != domain]
        if not domain_producers or not other_producers:
            return 0.0

        if not self._table_exists("producer_correlation"):
            return 0.0

        penalties: list[float] = []
        for p_a in domain_producers:
            for p_b in other_producers:
                corr = self._latest_pair_correlation(
                    p_a,
                    p_b,
                    symbol=symbol,
                    regime=regime,
                )
                if corr is None:
                    continue
                penalties.append(abs(corr) * 0.5)

        if not penalties:
            return 0.0

        return _clamp(max(penalties), 0.0, 0.5)

    def _table_exists(self, table_name: str) -> bool:
        row = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _latest_pair_correlation(self, producer_a: str, producer_b: str, *, symbol: str, regime: str) -> float | None:
        row = self._conn.execute(
            """
            SELECT pearson_r
            FROM producer_correlation
            WHERE ((producer_a = ? AND producer_b = ?) OR (producer_a = ? AND producer_b = ?))
              AND pearson_r IS NOT NULL
            ORDER BY
                CASE
                    WHEN UPPER(asset) = UPPER(?) THEN 0
                    WHEN UPPER(asset) = 'ALL' THEN 1
                    ELSE 2
                END,
                CASE
                    WHEN UPPER(regime) = UPPER(?) THEN 0
                    WHEN UPPER(regime) = 'UNKNOWN' THEN 1
                    ELSE 2
                END,
                datetime(last_updated) DESC
            LIMIT 1
            """,
            (producer_a, producer_b, producer_b, producer_a, str(symbol or ""), str(regime or "unknown")),
        ).fetchone()
        if row is None:
            return None
        return float(row[0])


def _brier_to_multiplier(brier: float) -> float:
    """Convert Brier score to weight multiplier."""
    if brier <= 0.10:
        return 1.5
    if brier <= 0.20:
        return 1.3
    if brier <= 0.25:
        return 1.0
    if brier <= 0.30:
        return 0.85
    return 0.70


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))
