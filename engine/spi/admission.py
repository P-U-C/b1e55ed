"""Single admission pipeline for SPI signals.

Both adapter-mediated and native SPI submissions call accept_signal().
This ensures identical internal outcomes regardless of ingress mode.
"""

from __future__ import annotations

import json
import uuid
import weakref
from datetime import datetime, timedelta

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.spi.models import AcceptedSignal

# Fix 2: Guard _ensure_tables() against repeated DDL on hot path.
# WeakSet holds live DB references; entry is auto-removed when the object is GC'd,
# so a new connection with the same address is correctly handled.  The DB singleton
# pattern means this fires only once per process in production.
_TABLES_ENSURED: weakref.WeakSet = weakref.WeakSet()


def _horizon_matches(h1: int, h2: int) -> bool:
    """Check if two horizon values are in the same bucket or within ±2h."""
    buckets = [(0, 2), (3, 5), (6, 18), (19, 48)]
    for lo, hi in buckets:
        if lo <= h1 <= hi and lo <= h2 <= hi:
            return True
    return abs(h1 - h2) <= 2


def find_or_create_cluster(
    db,
    *,
    signal_id: str,
    producer_id: str,
    symbol: str,
    direction: str,
    confidence: float,
    horizon_hours: int,
    now_iso: str,
) -> tuple[str, int, float]:
    """Find an existing cluster or create a new one.

    Returns (cluster_id, position, cluster_weight).
    """
    # Look for recent clusters matching symbol + direction
    lookback_minutes = max(horizon_hours * 15, 15)
    cutoff = (datetime.fromisoformat(now_iso) - timedelta(minutes=lookback_minutes)).isoformat()

    rows = (
        db.fetchall(
            """
        SELECT cluster_id, avg_confidence, horizon_hours, signal_count
        FROM spi_signal_clusters
        WHERE symbol = ? AND direction = ?
          AND datetime(substr(created_at, 1, 19)) >= datetime(?)
        ORDER BY created_at DESC
        """,
            (symbol, direction, cutoff[:19]),
        )
        if hasattr(db, "fetchall")
        else db.execute(
            """
        SELECT cluster_id, avg_confidence, horizon_hours, signal_count
        FROM spi_signal_clusters
        WHERE symbol = ? AND direction = ?
          AND datetime(substr(created_at, 1, 19)) >= datetime(?)
        ORDER BY created_at DESC
        """,
            (symbol, direction, cutoff[:19]),
        ).fetchall()
    )

    for row in rows:
        c_id, c_conf, c_horizon, c_count = row
        if abs(confidence - c_conf) <= 0.10 and _horizon_matches(horizon_hours, c_horizon):
            # Match found — join this cluster
            new_count = c_count + 1
            position = new_count
            weight = 1.0 / (position**1.5)
            # Update cluster stats
            new_avg_conf = (c_conf * c_count + confidence) / new_count
            db.execute(
                """
                UPDATE spi_signal_clusters
                SET signal_count = ?, avg_confidence = ?, updated_at = ?
                WHERE cluster_id = ?
                """,
                (new_count, new_avg_conf, now_iso, c_id),
            )
            return c_id, position, weight

    # No match — create new cluster
    cluster_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO spi_signal_clusters (
            cluster_id, symbol, direction, avg_confidence, horizon_hours,
            first_signal_id, first_producer_id, signal_count, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,1,?,?)
        """,
        (cluster_id, symbol, direction, confidence, horizon_hours, signal_id, producer_id, now_iso, now_iso),
    )
    return cluster_id, 1, 1.0


def accept_signal(
    *,
    producer_id: str,
    signal_client_id: str,
    submission_id: str,
    symbol: str,
    direction: str,
    confidence: float,
    horizon_hours: int,
    ingress_mode: str = "adapter",
    event_id: str | None = None,
    signal_payload: dict | None = None,
    db,  # engine.core.database.Database instance
) -> AcceptedSignal:
    """Accept a signal into the SPI system.

    Validates, assigns canonical ID, sets attribution window, writes to spi_signals.
    Called by both adapter path and gateway path.

    Returns the AcceptedSignal record (idempotent — if signal_client_id+submission_id
    already exists, the INSERT OR IGNORE silently skips and the canonical DB row is
    returned so callers always get the true signal_id).
    """
    now = datetime.now(tz=UTC)
    signal_id = str(uuid.uuid4())
    window_start = now.isoformat()
    window_end = (now + timedelta(hours=horizon_hours)).isoformat()

    # Fix 3: Snapshot entry price at admission time for later resolution.
    # This avoids the race condition where prices drift before the window closes.
    if signal_payload is None:
        signal_payload = {}
    if "entry_price" not in signal_payload and "price" not in signal_payload:
        try:
            from engine.spi.price_feeds import fetch_price_usd  # noqa: PLC0415

            live_price = fetch_price_usd(symbol, timeout_sec=3)
            if live_price is not None:
                signal_payload = {**signal_payload, "entry_price": live_price}
        except Exception:  # noqa: BLE001
            pass  # entry_price stays absent; resolution will mark expired

    signal_payload_json = json.dumps(signal_payload) if signal_payload else None

    accepted = AcceptedSignal(
        signal_id=signal_id,
        signal_client_id=signal_client_id,
        submission_id=submission_id,
        producer_id=producer_id,
        ingress_mode=ingress_mode,
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        horizon_hours=horizon_hours,
        submitted_at=now.isoformat(),
        attribution_window_start=window_start,
        attribution_window_end=window_end,
        status="accepted",
        event_id=event_id,
        signal_payload_json=signal_payload_json,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )

    # Ensure tables exist then write the record.
    _ensure_tables(db)

    # Clustering: find or create a cluster for deduplication
    cluster_id, cluster_position, cluster_weight = find_or_create_cluster(
        db,
        signal_id=signal_id,
        producer_id=producer_id,
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        horizon_hours=horizon_hours,
        now_iso=now.isoformat(),
    )
    accepted.cluster_id = cluster_id
    accepted.cluster_position = cluster_position
    accepted.cluster_weight = cluster_weight

    db.execute(
        """
        INSERT OR IGNORE INTO spi_signals (
            signal_id, signal_client_id, submission_id, producer_id,
            ingress_mode, symbol, direction, confidence, horizon_hours,
            submitted_at, attribution_window_start, attribution_window_end,
            status, event_id, signal_payload_json,
            cluster_id, cluster_position, cluster_weight,
            created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            accepted.signal_id,
            accepted.signal_client_id,
            accepted.submission_id,
            accepted.producer_id,
            accepted.ingress_mode,
            accepted.symbol,
            accepted.direction,
            accepted.confidence,
            accepted.horizon_hours,
            accepted.submitted_at,
            accepted.attribution_window_start,
            accepted.attribution_window_end,
            accepted.status,
            accepted.event_id,
            accepted.signal_payload_json,
            accepted.cluster_id,
            accepted.cluster_position,
            accepted.cluster_weight,
            accepted.created_at,
            accepted.updated_at,
        ),
    )

    # Fix 1: Fetch the canonical row from DB after INSERT OR IGNORE.
    # If this was a duplicate, the INSERT was silently skipped and `accepted.signal_id`
    # is a ghost UUID that doesn't exist in DB.  Always return the true DB record.
    existing = db.execute(
        "SELECT signal_id, signal_client_id, submission_id, producer_id, ingress_mode, "
        "symbol, direction, confidence, horizon_hours, submitted_at, "
        "attribution_window_start, attribution_window_end, status, event_id, "
        "signal_payload_json, cluster_id, cluster_position, cluster_weight, "
        "created_at, updated_at "
        "FROM spi_signals WHERE signal_client_id = ? AND submission_id = ?",
        (signal_client_id, submission_id),
    ).fetchone()
    if existing:
        # Return the canonical record (may differ from what we just tried to insert
        # if this was a duplicate submission).
        result = AcceptedSignal(
            signal_id=existing[0],
            signal_client_id=existing[1],
            submission_id=existing[2],
            producer_id=existing[3],
            ingress_mode=existing[4],
            symbol=existing[5],
            direction=existing[6],
            confidence=existing[7],
            horizon_hours=existing[8],
            submitted_at=existing[9],
            attribution_window_start=existing[10],
            attribution_window_end=existing[11],
            status=existing[12],
            event_id=existing[13],
            signal_payload_json=existing[14],
            cluster_id=existing[15],
            cluster_position=existing[16],
            cluster_weight=existing[17],
            created_at=existing[18],
            updated_at=existing[19],
        )
        # Phase 2B: auto-promote producer after signal acceptance
        try:
            from engine.spi.lifecycle import maybe_auto_promote  # noqa: PLC0415

            maybe_auto_promote(db, producer_id)
        except Exception as exc:  # noqa: BLE001
            import logging  # noqa: PLC0415

            logging.getLogger(__name__).warning(
                "spi_auto_promote_failed",
                extra={"producer_id": producer_id, "error": str(exc)},
            )
        return result

    return accepted  # fresh insert (shouldn't reach here but safe fallback)


def _ensure_tables(db) -> None:  # noqa: ANN001
    """Create SPI tables if they don't exist.

    Guarded by _TABLES_ENSURED so DDL is only issued once per DB connection
    rather than on every signal admission (hot-path guard).
    """
    if db in _TABLES_ENSURED:
        return

    db.execute("""CREATE TABLE IF NOT EXISTS spi_signals (
        signal_id TEXT PRIMARY KEY,
        signal_client_id TEXT NOT NULL,
        submission_id TEXT NOT NULL,
        producer_id TEXT NOT NULL,
        ingress_mode TEXT NOT NULL,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL,
        confidence REAL NOT NULL,
        horizon_hours INTEGER NOT NULL,
        submitted_at TEXT NOT NULL,
        attribution_window_start TEXT NOT NULL,
        attribution_window_end TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'accepted',
        resolved_at TEXT,
        event_id TEXT,
        signal_payload_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (signal_client_id, submission_id)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_spi_signals_producer_status ON spi_signals(producer_id, status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_spi_signals_window_end ON spi_signals(attribution_window_end, status)")

    db.execute("""CREATE TABLE IF NOT EXISTS spi_outcomes (
        outcome_id TEXT PRIMARY KEY,
        signal_id TEXT NOT NULL,
        producer_id TEXT NOT NULL,
        resolved_at TEXT NOT NULL,
        status TEXT NOT NULL,
        outcome_label TEXT,
        direction_correct INTEGER,
        entry_price REAL,
        exit_price REAL,
        price_change_pct REAL,
        resolution_method TEXT,
        brier_component REAL,
        karma_delta REAL,
        score_delta REAL,
        slash_applied INTEGER DEFAULT 0,
        slash_amount REAL DEFAULT 0,
        emission_earned REAL DEFAULT 0,
        chain_hash TEXT,
        event_id TEXT,
        created_at TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_spi_outcomes_producer ON spi_outcomes(producer_id, resolved_at)")

    db.execute("""CREATE TABLE IF NOT EXISTS spi_karma (
        producer_id TEXT NOT NULL,
        epoch INTEGER NOT NULL,
        epoch_brier REAL,
        epoch_karma REAL,
        running_karma REAL NOT NULL DEFAULT 0.5,
        resolved_count INTEGER DEFAULT 0,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (producer_id, epoch)
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS spi_producers (
        producer_id TEXT PRIMARY KEY,
        producer_name TEXT NOT NULL,
        lifecycle_state TEXT NOT NULL DEFAULT 'onboarding',
        ingress_mode TEXT NOT NULL DEFAULT 'adapter',
        registered_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")

    # Signal clustering table
    db.execute("""CREATE TABLE IF NOT EXISTS spi_signal_clusters (
        cluster_id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL,
        avg_confidence REAL NOT NULL,
        horizon_hours INTEGER NOT NULL,
        first_signal_id TEXT NOT NULL,
        first_producer_id TEXT NOT NULL,
        signal_count INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_spi_clusters_symbol_dir ON spi_signal_clusters(symbol, direction)")

    # Add cluster columns to spi_signals (idempotent via try/except)
    import contextlib  # noqa: PLC0415

    for col_sql in [
        "ALTER TABLE spi_signals ADD COLUMN cluster_id TEXT",
        "ALTER TABLE spi_signals ADD COLUMN cluster_position INTEGER DEFAULT 1",
        "ALTER TABLE spi_signals ADD COLUMN cluster_weight REAL DEFAULT 1.0",
    ]:
        with contextlib.suppress(Exception):
            db.execute(col_sql)

    _TABLES_ENSURED.add(db)
