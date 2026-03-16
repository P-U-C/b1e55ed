"""Single admission pipeline for SPI signals.

Both adapter-mediated and native SPI submissions call accept_signal().
This ensures identical internal outcomes regardless of ingress mode.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.spi.models import AcceptedSignal


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
    already exists, the INSERT OR IGNORE silently skips and the returned object
    reflects the new uuid, but the DB row is unchanged).
    """
    now = datetime.now(tz=UTC)
    signal_id = str(uuid.uuid4())
    window_start = now.isoformat()
    window_end = (now + timedelta(hours=horizon_hours)).isoformat()

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
        signal_payload_json=json.dumps(signal_payload) if signal_payload else None,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )

    # Ensure tables exist then write the record.
    _ensure_tables(db)
    db.execute(
        """
        INSERT OR IGNORE INTO spi_signals (
            signal_id, signal_client_id, submission_id, producer_id,
            ingress_mode, symbol, direction, confidence, horizon_hours,
            submitted_at, attribution_window_start, attribution_window_end,
            status, event_id, signal_payload_json, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            accepted.created_at,
            accepted.updated_at,
        ),
    )

    return accepted


def _ensure_tables(db) -> None:  # noqa: ANN001
    """Create SPI tables if they don't exist."""
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
