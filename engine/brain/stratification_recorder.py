"""engine.brain.stratification_recorder

Records benchmark comparison data into signal_stratification when a position closes.

For every closed position we:
1. Look up the system conviction score at entry.
2. Look up benchmark signals (signal.benchmark.v1) that were active at position open time.
3. Estimate what each benchmark would have earned using the same entry/exit prices.
4. Write one row per benchmark into signal_stratification for later analysis via
   ``b1e55ed report --stratification``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

try:
    from datetime import UTC
except ImportError:  # pragma: no cover
    UTC = UTC

from engine.core.database import Database

_log = logging.getLogger("b1e55ed.brain.stratification_recorder")

# How far to look back from position open time for benchmark signals.
_BENCHMARK_LOOKBACK_SECONDS = 3600  # 1 hour


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _benchmark_pnl(
    *,
    benchmark_direction: str,
    system_direction: str,
    system_pnl: float,
) -> float:
    """Estimate what a benchmark signal would have earned on this position.

    If the benchmark took the same direction as the system → same P&L.
    If opposite direction → negated P&L.
    If flat (no position) → zero.
    """
    bd = benchmark_direction.lower()
    if bd == "flat":
        return 0.0
    if bd == system_direction.lower():
        return system_pnl
    return -system_pnl


def record_benchmark_stratification(
    *,
    db: Database,
    position_id: str,
) -> int:
    """Record benchmark comparison rows for a closed position.

    Returns the number of rows written (one per benchmark source found).
    Silently returns 0 if the position is not closed or data is missing.
    """
    # ── 1. Load position ──────────────────────────────────────────────────
    pos = db.fetchone(
        """SELECT id, asset, direction, entry_price, size_notional,
                  opened_at, realized_pnl, conviction_id, status
           FROM positions WHERE id = ?""",
        (str(position_id),),
    )
    if pos is None:
        _log.debug("position %s not found, skipping stratification", position_id)
        return 0
    if str(pos["status"]) != "closed":
        _log.debug("position %s not closed (status=%s), skipping", position_id, pos["status"])
        return 0

    system_pnl: float = float(pos["realized_pnl"]) if pos["realized_pnl"] is not None else 0.0
    symbol: str = str(pos["asset"])
    system_direction: str = str(pos["direction"])
    opened_at_str: str = str(pos["opened_at"])

    # ── 2. Resolve system confidence from conviction_scores ───────────────
    system_confidence: float = 0.0
    conviction_id = pos["conviction_id"]
    if conviction_id is not None:
        cs = db.fetchone(
            "SELECT confidence FROM conviction_scores WHERE id = ?",
            (str(conviction_id),),
        )
        if cs is not None and cs["confidence"] is not None:
            system_confidence = float(cs["confidence"])

    # Derive confidence bucket (mirrors StratificationTracker logic).
    if system_confidence >= 0.65:
        bucket = "high"
    elif system_confidence >= 0.45:
        bucket = "mid"
    else:
        bucket = "low"

    # ── 3. Look up benchmark signals near position open time ──────────────
    try:
        opened_dt = datetime.fromisoformat(opened_at_str.replace("Z", "+00:00"))
        # Ensure timezone-aware.
        if opened_dt.tzinfo is None:
            opened_dt = opened_dt.replace(tzinfo=UTC)
    except (ValueError, AttributeError):
        _log.warning("could not parse opened_at=%r for position %s", opened_at_str, position_id)
        return 0

    window_start = (opened_dt - timedelta(seconds=_BENCHMARK_LOOKBACK_SECONDS)).isoformat()
    window_end = opened_dt.isoformat()

    benchmark_rows = db.fetchall(
        """SELECT payload, ts
           FROM events
           WHERE type = 'signal.benchmark.v1'
             AND ts >= ? AND ts <= ?
           ORDER BY ts DESC""",
        (window_start, window_end),
    )

    # Deduplicate: keep the most-recent signal per (source, symbol).
    seen: dict[tuple[str, str], dict] = {}
    for row in benchmark_rows:
        try:
            payload = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            continue
        bm_src = str(payload.get("source", "benchmark.unknown"))
        bm_sym = str(payload.get("symbol", "")).upper()
        if bm_sym != symbol.upper():
            continue
        key = (bm_src, bm_sym)
        if key not in seen:
            seen[key] = payload

    if not seen:
        _log.debug(
            "no benchmark signals found for %s near %s (window %s → %s)",
            symbol,
            position_id,
            window_start,
            window_end,
        )
        return 0

    # ── 4. Write rows to signal_stratification ────────────────────────────
    now = _utc_now().isoformat()
    written = 0
    for (bm_src, bm_sym), payload in seen.items():
        bm_dir = str(payload.get("direction", "flat")).lower()
        bm_pnl = _benchmark_pnl(
            benchmark_direction=bm_dir,
            system_direction=system_direction,
            system_pnl=system_pnl,
        )
        # Use a composite key so each (position, benchmark) pair is unique.
        sig_id = f"{position_id}:bm:{bm_src}"

        try:
            with db._lock, db.conn:
                db.execute(
                    """INSERT OR REPLACE INTO signal_stratification
                       (signal_id, symbol, confidence, bucket, direction,
                        created_at, outcome_pnl_usd, attributed_at,
                        position_id, benchmark_name, benchmark_direction, benchmark_pnl,
                        system_pnl, system_confidence, system_direction, recorded_at)
                       VALUES (?, ?, ?, ?, ?,
                               ?, ?, ?,
                               ?, ?, ?, ?,
                               ?, ?, ?, ?)""",
                    (
                        sig_id,
                        bm_sym,
                        system_confidence,
                        bucket,
                        system_direction,
                        opened_at_str,
                        system_pnl,
                        now,
                        str(position_id),
                        bm_src,
                        bm_dir,
                        bm_pnl,
                        system_pnl,
                        system_confidence,
                        system_direction,
                        now,
                    ),
                )
            written += 1
        except Exception:
            _log.warning("failed to write stratification row for %s / %s", position_id, bm_src, exc_info=True)

    _log.info(
        "stratification: wrote %d benchmark rows for position %s (%s %s, pnl=%.2f)",
        written,
        position_id,
        system_direction,
        symbol,
        system_pnl,
    )
    return written
