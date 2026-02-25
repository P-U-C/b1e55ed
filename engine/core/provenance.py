"""engine.core.provenance

Shared provenance computation logic — used by both the oracle REST endpoint
and the MCP tool so there is exactly one source of truth.

DESIGN PRINCIPLE:
  This module returns data, not judgements.  Callers decide what the data
  means.  No trust scores, no buy/sell signals — only verifiable history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from engine.core.database import Database


@dataclass
class AttributionWindow:
    """Signal statistics for a rolling time window."""

    signals: int
    hit_rate: float
    max_drawdown_pct: float


@dataclass
class ProvenanceResult:
    """Complete provenance record for a signal producer."""

    producer_id: str
    has_provenance: bool
    chain_verified: bool
    total_signals: int
    p_and_l_attributed: bool
    operator_coverage: int
    first_seen: str | None
    last_seen: str | None
    attribution_windows: dict[str, AttributionWindow] = field(default_factory=dict)
    note: str = ""


def compute_provenance(producer_id: str, db: Database) -> ProvenanceResult:
    """
    Compute full provenance for *producer_id*.

    Returns a :class:`ProvenanceResult` regardless of whether provenance data
    exists (check ``has_provenance``).
    """

    # -----------------------------------------------------------------------
    # 1. Basic event existence check
    # -----------------------------------------------------------------------
    row = db.conn.execute(
        "SELECT MIN(created_at), MAX(created_at), COUNT(*) FROM events WHERE source = ?",
        (producer_id,),
    ).fetchone()

    total_events = int(row[2]) if row else 0

    if total_events == 0:
        return ProvenanceResult(
            producer_id=producer_id,
            has_provenance=False,
            chain_verified=False,
            total_signals=0,
            p_and_l_attributed=False,
            operator_coverage=0,
            first_seen=None,
            last_seen=None,
            note=("No provenance data available. Proceeding without attribution context."),
        )

    first_seen: str | None = str(row[0]) if row[0] else None
    last_seen: str | None = str(row[1]) if row[1] else None

    # -----------------------------------------------------------------------
    # 2. Operator coverage (distinct contributors, used as proxy for node coverage)
    #    events.contributor_id references contributors.id, each of which has a
    #    unique node_id — so COUNT(DISTINCT contributor_id) ≈ distinct nodes.
    # -----------------------------------------------------------------------
    cov_row = db.conn.execute(
        "SELECT COUNT(DISTINCT contributor_id) FROM events WHERE source = ?",
        (producer_id,),
    ).fetchone()
    operator_coverage = int(cov_row[0]) if cov_row else 0

    # -----------------------------------------------------------------------
    # 3. Chain integrity (simplified: events with non-null, non-empty hashes)
    # -----------------------------------------------------------------------
    chain_row = db.conn.execute(
        "SELECT COUNT(*) FROM events WHERE source = ? AND hash IS NOT NULL AND hash != ''",
        (producer_id,),
    ).fetchone()
    chain_verified = bool(chain_row and int(chain_row[0]) > 0)

    # -----------------------------------------------------------------------
    # 4. P&L attribution: check if any conviction_scores for this producer
    #    have resolved outcomes (proxy for attribution to actual P&L).
    #    karma_settlements.intent_ids is a JSON list and does not directly
    #    reference producer_id, so we use the conviction_scores outcome as
    #    the canonical signal that outcomes were tracked.
    # -----------------------------------------------------------------------
    pnl_row = db.conn.execute(
        "SELECT COUNT(*) FROM conviction_scores WHERE node_id = ? AND outcome IS NOT NULL",
        (producer_id,),
    ).fetchone()
    p_and_l_attributed = bool(pnl_row and int(pnl_row[0]) > 0)

    # -----------------------------------------------------------------------
    # 5. Total signals (conviction_scores emitted by this producer as node)
    # -----------------------------------------------------------------------
    sig_row = db.conn.execute(
        "SELECT COUNT(*) FROM conviction_scores WHERE node_id = ?",
        (producer_id,),
    ).fetchone()
    total_signals = int(sig_row[0]) if sig_row else 0

    # -----------------------------------------------------------------------
    # 6. Attribution windows (7d, 30d, 90d)
    # -----------------------------------------------------------------------
    windows: dict[str, AttributionWindow] = {}
    for label, days in (("7d", 7), ("30d", 30), ("90d", 90)):
        cutoff = datetime.now(UTC) - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()

        w_row = db.conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN outcome IS NOT NULL AND outcome > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) AS known,
                MIN(CASE WHEN outcome IS NOT NULL THEN outcome ELSE NULL END) AS min_outcome
            FROM conviction_scores
            WHERE node_id = ? AND ts >= ?
            """,
            (producer_id, cutoff_iso),
        ).fetchone()

        if w_row is None:
            continue

        total_in_window = int(w_row[0])
        known_outcomes = int(w_row[2]) if w_row[2] is not None else 0

        if total_in_window == 0:
            continue

        wins = int(w_row[1]) if w_row[1] is not None else 0
        hit_rate = float(wins) / float(known_outcomes) if known_outcomes > 0 else 0.0
        min_outcome = float(w_row[3]) if w_row[3] is not None else 0.0
        max_drawdown_pct = min_outcome * 100.0 if min_outcome < 0 else 0.0

        windows[label] = AttributionWindow(
            signals=total_in_window,
            hit_rate=round(hit_rate, 4),
            max_drawdown_pct=round(max_drawdown_pct, 4),
        )

    return ProvenanceResult(
        producer_id=producer_id,
        has_provenance=True,
        chain_verified=chain_verified,
        total_signals=total_signals,
        p_and_l_attributed=p_and_l_attributed,
        operator_coverage=operator_coverage,
        first_seen=first_seen,
        last_seen=last_seen,
        attribution_windows=windows,
        note=("Provenance data available. Fields are informational only — interpret in context."),
    )
