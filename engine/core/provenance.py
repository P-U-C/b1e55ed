"""engine.core.provenance

Shared provenance computation logic — used by both the oracle REST endpoint
and the MCP tool so there is exactly one source of truth.

DESIGN PRINCIPLE:
  This module returns data, not judgements.  Callers decide what the data
  means.  No trust scores, no buy/sell signals — only verifiable history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017


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
    chain_verified: bool  # Deprecated alias kept for backwards compat; see chain_integrity_spot_checked
    chain_integrity_spot_checked: bool  # True if last 100 events passed hash-chain verification
    total_signals: int
    p_and_l_attributed: bool
    operator_coverage: int
    first_seen: str | None
    last_seen: str | None
    attribution_windows: dict[str, AttributionWindow] = field(default_factory=dict)
    note: str = ""


@dataclass(frozen=True)
class _IdentityResolution:
    """Resolved identity used for provenance lookup."""

    canonical_producer_id: str
    source_aliases: tuple[str, ...]
    contributor_ids: tuple[str, ...]


def _normalize_identity(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_identity(producer_id: str, db: Database) -> _IdentityResolution:
    """Resolve a producer query id into canonical + aliases.

    Canonical identity is contributor ``node_id`` when there is an unambiguous
    contributor match. Source aliases include historical ``events.source`` values
    observed for the same contributor so both ``source`` and ``node_id`` lookups
    converge to the same provenance record.
    """

    requested = _normalize_identity(producer_id) or str(producer_id)

    source_aliases: set[str] = {requested}
    contributor_ids: set[str] = set()
    node_candidates: set[str] = set()

    # 1) Direct contributor lookup (node_id or name)
    direct_rows = db.fetchall(
        "SELECT id, node_id, name FROM contributors WHERE node_id = ? OR name = ?",
        (requested, requested),
    )
    for row in direct_rows:
        cid = _normalize_identity(row["id"])
        node_id = _normalize_identity(row["node_id"])
        name = _normalize_identity(row["name"])

        if cid:
            contributor_ids.add(cid)
        if node_id:
            node_candidates.add(node_id)
            source_aliases.add(node_id)
        if name:
            source_aliases.add(name)

    # 2) Source lookup: source string may be an alias for a contributor node.
    by_source_rows = db.fetchall(
        "SELECT DISTINCT contributor_id FROM events WHERE source = ? AND contributor_id IS NOT NULL",
        (requested,),
    )
    for row in by_source_rows:
        cid = _normalize_identity(row[0])
        if cid:
            contributor_ids.add(cid)

    # 3) Expand aliases from contributor linkage (historical source values).
    if contributor_ids:
        contributor_ids_list = sorted(contributor_ids)
        placeholders = ",".join(["?"] * len(contributor_ids_list))

        contributor_rows = db.fetchall(
            f"SELECT id, node_id, name FROM contributors WHERE id IN ({placeholders})",
            tuple(contributor_ids_list),
        )
        for row in contributor_rows:
            node_id = _normalize_identity(row["node_id"])
            name = _normalize_identity(row["name"])
            if node_id:
                node_candidates.add(node_id)
                source_aliases.add(node_id)
            if name:
                source_aliases.add(name)

        source_rows = db.fetchall(
            f"SELECT DISTINCT source FROM events WHERE contributor_id IN ({placeholders}) AND source IS NOT NULL",
            tuple(contributor_ids_list),
        )
        for row in source_rows:
            src = _normalize_identity(row[0])
            if src:
                source_aliases.add(src)

    # Canonicalize when mapping is unambiguous to a single contributor node_id.
    canonical = requested
    if len(node_candidates) == 1:
        canonical = next(iter(node_candidates))
    elif requested in node_candidates:
        canonical = requested

    return _IdentityResolution(
        canonical_producer_id=canonical,
        source_aliases=tuple(sorted(source_aliases)),
        contributor_ids=tuple(sorted(contributor_ids)),
    )


def _build_signal_identity_filter(identity: _IdentityResolution) -> tuple[str, tuple[str, ...]]:
    """Build SQL predicate params for matching producer signal events."""

    clauses: list[str] = []
    params: list[str] = []

    if identity.source_aliases:
        placeholders = ",".join(["?"] * len(identity.source_aliases))
        clauses.append(f"source IN ({placeholders})")
        params.extend(identity.source_aliases)

    if identity.contributor_ids:
        placeholders = ",".join(["?"] * len(identity.contributor_ids))
        clauses.append(f"contributor_id IN ({placeholders})")
        params.extend(identity.contributor_ids)

    if not clauses:
        return "1 = 0", tuple()

    return f"({' OR '.join(clauses)})", tuple(params)


def _build_in_clause(column: str, values: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    if not values:
        return "1 = 0", tuple()
    placeholders = ",".join(["?"] * len(values))
    return f"{column} IN ({placeholders})", values


def compute_provenance(producer_id: str, db: Database) -> ProvenanceResult:
    """
    Compute full provenance for *producer_id*.

    Returns a :class:`ProvenanceResult` regardless of whether provenance data
    exists (check ``has_provenance``).
    """

    identity = _resolve_identity(producer_id, db)
    signal_filter_sql, signal_filter_params = _build_signal_identity_filter(identity)

    # -----------------------------------------------------------------------
    # 1. Signal existence + first/last seen (canonicalized over source aliases
    #    and contributor linkage).
    # -----------------------------------------------------------------------
    row = db.fetchone(
        f"""
        SELECT MIN(created_at), MAX(created_at), COUNT(*)
        FROM events
        WHERE type LIKE 'signal.%' AND {signal_filter_sql}
        """,
        signal_filter_params,
    )

    total_signals = int(row[2]) if row else 0

    if total_signals == 0:
        return ProvenanceResult(
            producer_id=identity.canonical_producer_id,
            has_provenance=False,
            chain_verified=False,
            chain_integrity_spot_checked=False,
            total_signals=0,
            p_and_l_attributed=False,
            operator_coverage=0,
            first_seen=None,
            last_seen=None,
            note=("No provenance data available. Proceeding without attribution context."),
        )

    assert row is not None  # COUNT(*) always returns a row; guarded by total_signals check above
    first_seen: str | None = str(row[0]) if row[0] else None
    last_seen: str | None = str(row[1]) if row[1] else None

    # -----------------------------------------------------------------------
    # 2. Operator coverage (distinct contributors for matched signals)
    # -----------------------------------------------------------------------
    cov_row = db.fetchone(
        f"""
        SELECT COUNT(DISTINCT contributor_id)
        FROM events
        WHERE type LIKE 'signal.%' AND contributor_id IS NOT NULL AND {signal_filter_sql}
        """,
        signal_filter_params,
    )
    operator_coverage = int(cov_row[0]) if cov_row else 0

    # -----------------------------------------------------------------------
    # 3. Chain integrity — spot-check last 100 events in the full chain.
    #    We verify the global chain (not per-producer) since the chain is
    #    contiguous across all producers.  fast=True verifies last 2000 by
    #    default; we override to last 100 for a lightweight beta check.
    #
    #    Ralph Merkle described this integrity property in his 1979 doctoral
    #    thesis: alter any node and the divergence propagates up the tree.
    #    The mechanism predates "blockchain" as a term by three decades.
    # -----------------------------------------------------------------------
    try:
        chain_integrity_spot_checked = db.verify_hash_chain(fast=True, last_n=100)
    except Exception:
        chain_integrity_spot_checked = False
    chain_verified = chain_integrity_spot_checked  # backwards-compat alias

    # -----------------------------------------------------------------------
    # 4. Outcome attribution from conviction_scores.
    #    We resolve by canonical id + aliases so source/node_id queries share
    #    one identity surface.
    # -----------------------------------------------------------------------
    score_node_ids = tuple(sorted({x for x in (identity.canonical_producer_id, *identity.source_aliases) if x}))
    score_filter_sql, score_filter_params = _build_in_clause("node_id", score_node_ids)

    pnl_row = db.fetchone(
        f"SELECT COUNT(*) FROM conviction_scores WHERE {score_filter_sql} AND outcome IS NOT NULL",
        score_filter_params,
    )
    p_and_l_attributed = bool(pnl_row and int(pnl_row[0]) > 0)

    # -----------------------------------------------------------------------
    # 5. Attribution windows (7d, 30d, 90d)
    # -----------------------------------------------------------------------
    windows: dict[str, AttributionWindow] = {}
    for label, days in (("7d", 7), ("30d", 30), ("90d", 90)):
        cutoff = datetime.now(UTC) - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()

        w_row = db.fetchone(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN outcome IS NOT NULL AND outcome > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) AS known,
                MIN(CASE WHEN outcome IS NOT NULL THEN outcome ELSE NULL END) AS min_outcome
            FROM conviction_scores
            WHERE {score_filter_sql} AND ts >= ?
            """,
            (*score_filter_params, cutoff_iso),
        )

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
        producer_id=identity.canonical_producer_id,
        has_provenance=True,
        chain_verified=chain_verified,
        chain_integrity_spot_checked=chain_integrity_spot_checked,
        total_signals=total_signals,
        p_and_l_attributed=p_and_l_attributed,
        operator_coverage=operator_coverage,
        first_seen=first_seen,
        last_seen=last_seen,
        attribution_windows=windows,
        note=(
            "Provenance data available. Queries resolve contributor node_id and observed source aliases to a "
            "canonical producer identity. Fields are informational only — interpret in context. "
            "chain_integrity_spot_checked: last 100 events verified against their stored hashes."
        ),
    )
