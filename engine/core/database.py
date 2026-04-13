"""engine.core.database

A grimoire is not a textbook — it is a book of hard-won procedures.

This database is the journal: append-only events with a hash chain.
If you cannot remember the past, you will repeat it.
"""

from __future__ import annotations

import json
import logging as _logging
import sqlite3
import threading
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.core.events import EventType, canonical_json
from engine.core.exceptions import EventStoreError
from engine.core.models import Event, compute_event_hash

_logger = _logging.getLogger("b1e55ed.database")

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

SCHEMA = """
-- ============================================================
-- Schema Version Tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Core Events (hash chain, append-only)
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    ts TEXT NOT NULL,
    observed_at TEXT,
    source TEXT,
    contributor_id TEXT,
    trace_id TEXT,
    schema_version TEXT DEFAULT 'v1',
    dedupe_key TEXT,
    payload TEXT NOT NULL,
    prev_hash TEXT,
    hash TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT (datetime('now')),
    symbol TEXT GENERATED ALWAYS AS (json_extract(payload, '$.symbol')) VIRTUAL
);

CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_dedupe ON events(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
CREATE INDEX IF NOT EXISTS idx_events_contributor ON events(contributor_id);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);

-- ============================================================
-- Event Deduplication
-- ============================================================
CREATE TABLE IF NOT EXISTS event_dedup (
    dedupe_key TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id),
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_dedup_event_id ON event_dedup(event_id);

-- ============================================================
-- Feature Snapshots (reproducibility)
-- ============================================================
CREATE TABLE IF NOT EXISTS feature_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ts TEXT NOT NULL,
    features TEXT NOT NULL,
    source_event_ids TEXT,
    regime TEXT,
    version TEXT DEFAULT 'v1',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_snapshots_cycle ON feature_snapshots(cycle_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_symbol ON feature_snapshots(symbol);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON feature_snapshots(ts);

-- ============================================================
-- Conviction Scores
-- ============================================================
CREATE TABLE IF NOT EXISTS conviction_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT,
    node_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('long', 'short', 'neutral')),
    magnitude REAL NOT NULL CHECK(magnitude >= 0 AND magnitude <= 10),
    timeframe TEXT NOT NULL,
    ts TEXT NOT NULL,
    commitment_hash TEXT NOT NULL,
    signature TEXT,
    pcs_score REAL,
    cts_score REAL,
    regime TEXT,
    domains_used TEXT,
    confidence REAL,
    metadata TEXT,
    outcome REAL,
    outcome_ts TEXT
);

CREATE INDEX IF NOT EXISTS idx_scores_symbol ON conviction_scores(symbol);
CREATE INDEX IF NOT EXISTS idx_scores_ts ON conviction_scores(ts);
CREATE INDEX IF NOT EXISTS idx_scores_node ON conviction_scores(node_id);
CREATE INDEX IF NOT EXISTS idx_scores_cycle ON conviction_scores(cycle_id);
CREATE INDEX IF NOT EXISTS idx_scores_symbol_ts ON conviction_scores(symbol, ts DESC);

-- ============================================================
-- Positions (projection from events)
-- ============================================================
CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    asset TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('long', 'short')),
    entry_price REAL NOT NULL,
    size_notional REAL NOT NULL,
    leverage REAL DEFAULT 1.0,
    margin_type TEXT DEFAULT 'isolated' CHECK(margin_type IN ('isolated', 'cross')),
    stop_loss REAL,
    take_profit REAL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    status TEXT DEFAULT 'open' CHECK(status IN (
        'open', 'monitoring', 'degrading', 'closing', 'closed', 'liquidated'
    )),
    realized_pnl REAL,
    conviction_id INTEGER,
    regime_at_entry TEXT,
    pcs_at_entry REAL,
    cts_at_entry REAL,
    max_drawdown_during REAL,
    max_favorable_during REAL
);

CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_asset ON positions(asset);

-- ============================================================
-- Orders
-- ============================================================
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    position_id TEXT REFERENCES positions(id),
    venue TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('market', 'limit', 'stop', 'stop_limit')),
    side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
    symbol TEXT NOT NULL,
    size REAL NOT NULL,
    price REAL,
    stop_price REAL,
    fill_price REAL,
    fill_size REAL,
    status TEXT DEFAULT 'pending' CHECK(status IN (
        'pending', 'submitted', 'partial', 'filled', 'canceled', 'rejected', 'failed'
    )),
    idempotency_key TEXT UNIQUE,
    created_at TEXT DEFAULT (datetime('now')),
    filled_at TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_position ON orders(position_id);

-- ============================================================
-- Balances
-- ============================================================
CREATE TABLE IF NOT EXISTS balances (
    venue TEXT NOT NULL,
    asset TEXT NOT NULL,
    amount REAL NOT NULL,
    last_reconciled TEXT NOT NULL,
    PRIMARY KEY (venue, asset)
);

-- ============================================================
-- Karma Intents
-- ============================================================
CREATE TABLE IF NOT EXISTS karma_intents (
    id TEXT PRIMARY KEY,
    trade_id TEXT NOT NULL UNIQUE,
    contributor_id TEXT,
    realized_pnl_usd REAL NOT NULL,
    karma_percentage REAL NOT NULL,
    karma_amount_usd REAL NOT NULL,
    node_id TEXT NOT NULL,
    signature TEXT,
    settled INTEGER DEFAULT 0,
    batch_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_karma_intents_settled ON karma_intents(settled);

-- ============================================================
-- Karma Settlements
-- ============================================================
CREATE TABLE IF NOT EXISTS karma_settlements (
    id TEXT PRIMARY KEY,
    intent_ids TEXT NOT NULL,
    total_usd REAL NOT NULL,
    destination_wallet TEXT NOT NULL,
    tx_hash TEXT,
    status TEXT DEFAULT 'pending' CHECK(status IN (
        'pending', 'submitted', 'confirmed', 'failed'
    )),
    signature TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Conviction Log (learning data)
-- ============================================================
CREATE TABLE IF NOT EXISTS conviction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    domain TEXT NOT NULL,
    domain_score REAL NOT NULL,
    domain_weight REAL NOT NULL,
    weighted_contribution REAL NOT NULL,
    producer_name TEXT NOT NULL DEFAULT '',
    event_id TEXT NOT NULL DEFAULT '',
    contribution_weight REAL NOT NULL DEFAULT 1.0,
    feature_key TEXT,
    feature_value REAL,
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conviction_log_cycle ON conviction_log(cycle_id);
CREATE INDEX IF NOT EXISTS idx_conviction_log_symbol ON conviction_log(symbol);

CREATE TABLE IF NOT EXISTS forecast_attribution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    forecast_id TEXT NOT NULL,
    conviction_id TEXT NOT NULL,
    position_id TEXT,
    contribution_weight REAL NOT NULL,
    disposition TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_forecast_attribution_forecast ON forecast_attribution(forecast_id);
CREATE INDEX IF NOT EXISTS idx_forecast_attribution_conviction ON forecast_attribution(conviction_id);

-- ============================================================
-- Producer Health
-- ============================================================
CREATE TABLE IF NOT EXISTS producer_health (
    name TEXT PRIMARY KEY,
    domain TEXT,
    schedule TEXT,
    endpoint TEXT,
    last_run_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    events_produced INTEGER DEFAULT 0,
    avg_duration_ms REAL,
    expected_interval_ms INTEGER,
    quarantined_until TEXT,
    quarantined_reason TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Learning Weights (adjustment history)
-- ============================================================
CREATE TABLE IF NOT EXISTS learning_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_type TEXT NOT NULL CHECK(cycle_type IN ('daily', 'weekly', 'monthly')),
    domain TEXT NOT NULL,
    old_weight REAL NOT NULL,
    new_weight REAL NOT NULL,
    delta REAL NOT NULL,
    reason TEXT,
    approved INTEGER DEFAULT 0,
    approved_by TEXT,
    ts TEXT NOT NULL,
    reverted INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_learning_weights_ts ON learning_weights(ts);

-- ============================================================
-- Producer Scores (learning data)
-- ============================================================
CREATE TABLE IF NOT EXISTS producer_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producer TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    signals_emitted INTEGER NOT NULL,
    signals_correct INTEGER NOT NULL,
    accuracy REAL NOT NULL,
    staleness_rate REAL NOT NULL,
    error_rate REAL NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_producer_scores_producer ON producer_scores(producer);

-- ============================================================
-- Producer Karma (flywheel attribution)
-- ============================================================
CREATE TABLE IF NOT EXISTS producer_karma (
    producer_id TEXT PRIMARY KEY,
    karma_score REAL DEFAULT 1.0,
    win_count INTEGER DEFAULT 0,
    loss_count INTEGER DEFAULT 0,
    total_trades INTEGER DEFAULT 0,
    last_updated TEXT
);

-- ============================================================
-- Producer Karma Config (DeerFlow S0 — volume dampening + LLM ceiling)
-- Eigentrust (Kamvar et al., 2003): trust is not given. It is computed from outcomes.
-- Initial ceiling 0.3 for LLM sources. Each validated trade lifts it by 0.1.
-- The table remembers what the model earned, not what it claimed.
-- ============================================================
CREATE TABLE IF NOT EXISTS producer_karma_config (
    producer_name TEXT PRIMARY KEY,
    karma_ceiling REAL NOT NULL DEFAULT 1.0,
    source_type TEXT,
    ceiling_validated_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

-- ============================================================
-- API Rate Limiting (SEC1)
-- ============================================================
CREATE TABLE IF NOT EXISTS api_rate_limits (
    key TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    window_seconds INTEGER NOT NULL,
    count INTEGER NOT NULL,
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (key, window_start, window_seconds)
);

CREATE INDEX IF NOT EXISTS idx_api_rate_limits_key ON api_rate_limits(key);

-- ============================================================
-- System State (key-value store for kill switch state etc.)
-- ============================================================
CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Risk Triggers (audit)
-- ============================================================
CREATE TABLE IF NOT EXISTS risk_triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_type TEXT NOT NULL,
    level INTEGER,
    details TEXT,
    ts TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Audit Log
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT DEFAULT (datetime('now')),
    action TEXT NOT NULL,
    actor TEXT,
    component TEXT,
    details TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);

-- ============================================================
-- Pattern Matches (corpus integration)
-- ============================================================
CREATE TABLE IF NOT EXISTS pattern_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id TEXT NOT NULL,
    matched_at TEXT NOT NULL,
    market_state TEXT,
    boost_applied TEXT,
    outcome REAL,
    outcome_ts TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Webhook Subscriptions (outbound notifications)
-- ============================================================
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    event_globs TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_enabled ON webhook_subscriptions(enabled);

-- ============================================================
-- Contributors + Attribution
-- ============================================================
CREATE TABLE IF NOT EXISTS contributors (
    id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'tester',
    metadata TEXT DEFAULT '{}',
    registered_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(node_id)
);

CREATE TABLE IF NOT EXISTS contributor_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contributor_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    signal_direction TEXT,
    signal_score REAL,
    signal_asset TEXT,
    accepted INTEGER DEFAULT 0,
    profitable INTEGER DEFAULT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (contributor_id) REFERENCES contributors(id)
);

CREATE INDEX IF NOT EXISTS idx_contrib_signals_contributor ON contributor_signals(contributor_id);
CREATE INDEX IF NOT EXISTS idx_contrib_signals_asset ON contributor_signals(signal_asset);

-- ============================================================
-- Signal Stratification (flywheel S7)
-- ============================================================
CREATE TABLE IF NOT EXISTS signal_stratification (
    signal_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    confidence REAL NOT NULL,
    bucket TEXT NOT NULL,
    direction TEXT NOT NULL,
    created_at TEXT NOT NULL,
    outcome_pnl_usd REAL,
    attributed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_signal_strat_bucket ON signal_stratification(bucket);

-- ============================================================
-- Discretionary Signals (operator-injected benchmarks)
-- ============================================================
CREATE TABLE IF NOT EXISTS discretionary_signals (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    confidence REAL NOT NULL,
    reasoning TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_discretionary_symbol ON discretionary_signals(symbol);

-- ============================================================
-- Learnable Scoring Parameters (P2.4)
-- ============================================================
CREATE TABLE IF NOT EXISTS scoring_params (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    param_key TEXT NOT NULL UNIQUE,
    producer_name TEXT NOT NULL,
    param_type TEXT NOT NULL,
    value_default REAL NOT NULL,
    value_shadow REAL NOT NULL,
    value_live REAL NOT NULL,
    shadow_mode INTEGER NOT NULL DEFAULT 1,
    last_updated TEXT NOT NULL DEFAULT (datetime('now')),
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_sp_producer ON scoring_params(producer_name);

-- ============================================================
-- Producer Correlation Matrix (P2.3)
-- ============================================================
CREATE TABLE IF NOT EXISTS producer_correlation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    computed_at REAL,
    producer_a TEXT NOT NULL,
    producer_b TEXT NOT NULL,
    asset TEXT NOT NULL DEFAULT 'ALL',
    horizon TEXT NOT NULL DEFAULT '24h',
    regime TEXT NOT NULL DEFAULT 'unknown',
    pearson_r REAL,
    agreement_rate REAL,
    agreement_win_rate REAL,
    disagreement_win_rate_a REAL,
    sample_count INTEGER NOT NULL DEFAULT 0,
    window_days INTEGER NOT NULL DEFAULT 30,
    last_updated TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(producer_a, producer_b, asset, regime)
);
CREATE INDEX IF NOT EXISTS idx_pc_pair ON producer_correlation(producer_a, producer_b);

-- ============================================================
-- Forecast Resolution + Meta Producer Performance (P4.4)
-- ============================================================
CREATE TABLE IF NOT EXISTS forecast_resolution_state (
    forecast_event_id TEXT PRIMARY KEY,
    resolved_at REAL,
    outcome_event_id TEXT
);

CREATE TABLE IF NOT EXISTS producer_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    computed_at REAL NOT NULL,
    producer_id TEXT NOT NULL,
    asset TEXT NOT NULL,
    horizon TEXT NOT NULL,
    regime TEXT NOT NULL DEFAULT 'all',
    window_days INTEGER NOT NULL,
    forecast_count INTEGER NOT NULL,
    win_rate REAL,
    avg_brier REAL,
    avg_confidence REAL,
    confidence_reliability REAL
);
CREATE INDEX IF NOT EXISTS idx_pp_lookup ON producer_performance(producer_id, asset, horizon, regime, computed_at DESC);

-- ============================================================
-- Forecast Calibration (P2.1)
-- ============================================================
CREATE TABLE IF NOT EXISTS forecast_calibration (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    forecast_id TEXT NOT NULL UNIQUE,
    producer_name TEXT NOT NULL,
    asset TEXT NOT NULL,
    regime TEXT NOT NULL DEFAULT 'unknown',
    horizon TEXT NOT NULL,
    direction TEXT NOT NULL,           -- 'bullish' | 'bearish' | 'neutral'
    confidence REAL NOT NULL,
    calibrated INTEGER NOT NULL DEFAULT 0,  -- 0 = raw, 1 = isotonic-adjusted
    outcome REAL,                      -- 1.0 (hit) | 0.0 (miss) | NULL (unresolved)
    brier_score REAL,                  -- computed on resolution: (confidence - outcome)^2
    price_at_emit REAL,                -- price when forecast was emitted (if available)
    price_at_resolve REAL,             -- price when resolved
    emitted_at TEXT NOT NULL,
    resolved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_fc_producer ON forecast_calibration(producer_name);
CREATE INDEX IF NOT EXISTS idx_fc_unresolved ON forecast_calibration(resolved_at) WHERE resolved_at IS NULL;

-- ============================================================
-- Producer Calibration Curves (P2.2)
-- ============================================================
CREATE TABLE IF NOT EXISTS producer_calibration (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producer_name TEXT NOT NULL,
    asset TEXT NOT NULL DEFAULT 'ALL',
    regime TEXT NOT NULL DEFAULT 'unknown',
    confidence_bucket TEXT NOT NULL,
    observed_win_rate REAL,
    mean_brier_score REAL,
    sample_count INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(producer_name, asset, regime, confidence_bucket)
);

-- ============================================================
-- LLM Critic Shadow Log (P3.1)
-- ============================================================
CREATE TABLE IF NOT EXISTS llm_shadow_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producer TEXT NOT NULL,
    asset TEXT NOT NULL,
    horizon TEXT NOT NULL,
    regime TEXT NOT NULL,
    rule_confidence REAL NOT NULL,
    llm_confidence_delta REAL NOT NULL,
    llm_suppressed INTEGER NOT NULL DEFAULT 0,
    llm_rationale TEXT,
    llm_error TEXT,
    shadow_mode INTEGER NOT NULL DEFAULT 1,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_shadow_producer_ts ON llm_shadow_log(producer, ts);

-- ============================================================
-- Signal Log (dashboard signal history, time-series confidence)
-- ============================================================
CREATE TABLE IF NOT EXISTS signal_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producer_id TEXT NOT NULL,
    domain TEXT,
    asset TEXT,
    direction TEXT,
    confidence REAL,
    score REAL,
    source TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_signal_log_producer ON signal_log(producer_id);
CREATE INDEX IF NOT EXISTS idx_signal_log_created ON signal_log(created_at);

-- Karma Chain Queue (ERC-8004 E2 — on-chain reputation writes)
-- ============================================================
CREATE TABLE IF NOT EXISTS karma_chain_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL,
    karma_delta REAL NOT NULL,
    forecast_id TEXT NOT NULL,
    producer_node_id TEXT NOT NULL,
    outcome_json TEXT,
    status TEXT DEFAULT 'pending',
    tx_hash TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    submitted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_karma_chain_queue_status ON karma_chain_queue(status);
CREATE INDEX IF NOT EXISTS idx_karma_chain_queue_forecast ON karma_chain_queue(forecast_id);
"""


def _dt_to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _iso_to_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    # Accept Z suffix
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass
class Database:
    """Event-sourced SQLite database with hash chain."""

    # dataclass auto-generates __eq__ which sets __hash__ = None; restore it
    # so Database instances are usable in sets/weakrefs (identity-based hash).
    __hash__ = object.__hash__

    db_path: Path

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        # Set connection-level pragmas before any other DB operations.
        # These MUST run before _init_schema() and outside any transaction:
        # journal_mode=WAL cannot be changed inside a transaction, and
        # executescript() in _init_schema has unpredictable transaction state.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._cleanup_counter = 0  # throttle for periodic rate_limits cleanup
        self._init_schema()
        self._last_hash = self._get_last_hash()

    def close(self) -> None:
        self.conn.close()

    # Seventy-one voices, one gate. The lock does not slow the crowd;
    # it keeps the crowd from becoming a mob.
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Thread-safe execute. Use this instead of db.conn.execute() in API routes."""
        with self._lock:
            return self.conn.execute(sql, params)

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        """Fetch a single row, holding the lock throughout."""
        with self._lock:
            return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Fetch all rows, holding the lock throughout."""
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA)
            # WAL + synchronous are now set in __post_init__ before this method
            # runs, so they apply before any schema operations.
            self.conn.execute("PRAGMA foreign_keys=ON")

        # Lightweight migrations for additive columns (SQLite-friendly).
        self._ensure_column("events", "contributor_id", "TEXT")
        self._ensure_column("events", "hash_version", "INT DEFAULT 1")
        self._ensure_column("karma_intents", "contributor_id", "TEXT")
        self._ensure_column("conviction_log", "producer_name", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("conviction_log", "event_id", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("conviction_log", "contribution_weight", "REAL NOT NULL DEFAULT 1.0")
        # Popper: a conviction that cannot be traced to evidence is not a conviction -- it is a preference. feature_key is the evidence.
        self._ensure_column("conviction_log", "feature_key", "TEXT")
        self._ensure_column("conviction_log", "feature_value", "REAL")
        # P2.3 — producer correlation matrix
        self._ensure_table_exists("producer_correlation")
        # P2.1 — forecast calibration
        self._ensure_table_exists("forecast_calibration")
        # P2.4 — learnable scoring parameters
        self._ensure_table_exists("scoring_params")
        # P2.2 — producer calibration curves
        self._ensure_table_exists("producer_calibration")
        # P3.1 — LLM critic shadow logging
        self._ensure_table_exists("llm_shadow_log")
        # P4.4 — outcome resolution + meta-producer performance tables
        self._ensure_resolution_tables()
        # P2.5 — isotonic calibration uses forecast_calibration (P2.1); no new table
        self._migrate_karma_intents_unique_trade_id()
        # DeerFlow S0 — producer karma config (volume dampening + LLM ceiling)
        self._ensure_table_exists("producer_karma_config")
        # Retention fix: conviction_scores needs created_at for time-based pruning.
        # Default to datetime('now') so existing rows are treated as recent.
        self._ensure_column("conviction_scores", "created_at", "TEXT")
        # Performance: index on created_at (prevents linear scan on every insert)
        with self.conn:
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC)")
            # events.symbol: generated column replaces unindexable json_extract queries.
            # VIRTUAL generated columns can be added via ALTER TABLE on SQLite 3.31+.
            self._ensure_column(
                "events",
                "symbol",
                "TEXT GENERATED ALWAYS AS (json_extract(payload, '$.symbol')) VIRTUAL",
            )
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_events_symbol ON events(symbol)")
        # Benchmark stratification: additive columns for benchmark comparison rows.
        self._ensure_column("signal_stratification", "position_id", "TEXT")
        self._ensure_column("signal_stratification", "benchmark_name", "TEXT")
        self._ensure_column("signal_stratification", "benchmark_direction", "TEXT")
        self._ensure_column("signal_stratification", "benchmark_pnl", "REAL")
        self._ensure_column("signal_stratification", "system_pnl", "REAL")
        self._ensure_column("signal_stratification", "system_confidence", "REAL")
        self._ensure_column("signal_stratification", "system_direction", "TEXT")
        self._ensure_column("signal_stratification", "recorded_at", "TEXT")
        with self.conn:
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_strat_position ON signal_stratification(position_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_strat_benchmark ON signal_stratification(benchmark_name)")
        # ERC-8004 E1 — on-chain identity columns
        self._ensure_column("contributors", "agent_id", "INTEGER")
        self._ensure_column("contributors", "chain_tx_hash", "TEXT")
        # ERC-8004 E2 — karma chain queue for on-chain reputation writes
        self._ensure_table_exists("karma_chain_queue")
        # Horizon-based auto-close: track which horizon a position was opened from.
        # Also used for bias-flip scoping (same symbol + same horizon = same view).
        self._ensure_column("positions", "horizon_hours", "REAL")

    def _ensure_table_exists(self, table: str) -> None:
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table,),
        ).fetchone()
        if row is not None:
            return
        with self.conn:
            self.conn.executescript(SCHEMA)

    def _ensure_column(self, table: str, column: str, column_type: str) -> None:
        # Use table_xinfo (available since SQLite 3.26) instead of table_info:
        # table_xinfo includes virtual/hidden generated columns which table_info omits.
        cols = [str(r[1]) for r in self.conn.execute(f"PRAGMA table_xinfo({table})").fetchall()]
        if column in cols:
            return
        with self.conn:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    # Stratigraphy rule: add new layers, do not erase old artifacts.
    # These migrations are additive so the chain's history stays verifiable.
    def _ensure_resolution_tables(self) -> None:
        """Ensure additive tables/columns needed for forecast outcome resolution exist."""

        self._ensure_table_exists("forecast_resolution_state")
        self._ensure_table_exists("producer_performance")
        self._ensure_table_exists("producer_correlation")

        # producer_correlation existed before P4.4; add additive columns for the
        # new agreement-style matrix while preserving backwards compatibility.
        self._ensure_column("producer_correlation", "computed_at", "REAL")
        self._ensure_column("producer_correlation", "horizon", "TEXT NOT NULL DEFAULT '24h'")
        self._ensure_column("producer_correlation", "agreement_rate", "REAL")
        self._ensure_column("producer_correlation", "agreement_win_rate", "REAL")
        self._ensure_column("producer_correlation", "disagreement_win_rate_a", "REAL")

    def _migrate_karma_intents_unique_trade_id(self) -> None:
        """Rebuild karma_intents with UNIQUE(trade_id) and contributor_id if not already present.

        Safe to call on both fresh DBs (table already has constraint from SCHEMA) and
        existing DBs that predate the UNIQUE constraint.
        """
        row = self.conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='karma_intents'").fetchone()
        if row is None:
            return  # Table not yet created; SCHEMA will handle it.

        table_sql = str(row[0] or "").upper()
        # Detect whether trade_id already has a UNIQUE constraint in the DDL.
        if "UNIQUE" in table_sql:
            return  # Already migrated.

        # Rebuild: keep the earliest row per trade_id (deduplicate), add UNIQUE constraint.
        self.conn.execute("PRAGMA foreign_keys=OFF")
        try:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS karma_intents_new (
                    id TEXT PRIMARY KEY,
                    trade_id TEXT NOT NULL UNIQUE,
                    contributor_id TEXT,
                    realized_pnl_usd REAL NOT NULL,
                    karma_percentage REAL NOT NULL,
                    karma_amount_usd REAL NOT NULL,
                    node_id TEXT NOT NULL,
                    signature TEXT,
                    settled INTEGER DEFAULT 0,
                    batch_id TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
            # Copy unique trade_ids, keeping the first (by rowid).
            self.conn.execute(
                """
                INSERT OR IGNORE INTO karma_intents_new
                    (id, trade_id, realized_pnl_usd, karma_percentage, karma_amount_usd,
                     node_id, signature, settled, batch_id, created_at)
                SELECT id, trade_id, realized_pnl_usd, karma_percentage, karma_amount_usd,
                       node_id, signature, settled, batch_id, created_at
                FROM karma_intents
                WHERE rowid IN (
                    SELECT MIN(rowid) FROM karma_intents GROUP BY trade_id
                )
                """
            )
            self.conn.execute("DROP TABLE karma_intents")
            self.conn.execute("ALTER TABLE karma_intents_new RENAME TO karma_intents")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_karma_intents_settled ON karma_intents(settled)")
            self.conn.commit()
        finally:
            self.conn.execute("PRAGMA foreign_keys=ON")

    # Well-known genesis prev_hash — prevents chain-splice attacks where
    # any event could claim to be genesis by setting prev_hash=None.
    GENESIS_PREV_HASH = "0" * 64

    def _get_last_hash(self) -> str | None:
        row = self.conn.execute("SELECT hash FROM events ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
        if row is None:
            return self.GENESIS_PREV_HASH
        return str(row[0])

    @staticmethod
    def _payload_hash(payload: dict[str, Any]) -> str:
        import hashlib

        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    def _append_event_inner(
        self,
        *,
        event_type: EventType,
        payload: dict[str, Any],
        event_id: str | None = None,
        observed_at: datetime | None = None,
        source: str | None = None,
        contributor_id: str | None = None,
        trace_id: str | None = None,
        schema_version: str = "v1",
        dedupe_key: str | None = None,
        ts: datetime | None = None,
    ) -> Event:
        """Core append logic. Caller must hold self._lock.

        Does NOT open its own transaction — caller controls transaction boundary.
        This enables atomic batch appends.
        """

        now = ts or datetime.now(tz=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        payload_canon = json.loads(canonical_json(payload))
        p_hash = self._payload_hash(payload_canon)

        if dedupe_key is not None:
            row = self.conn.execute(
                "SELECT event_id, payload_hash FROM event_dedup WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            if row is not None:
                if str(row[1]) != p_hash:
                    import logging as _log

                    _log.getLogger("b1e55ed.database").warning("dedupe_key payload drift (keeping original): %s", dedupe_key)
                existing = self.conn.execute(
                    "SELECT * FROM events WHERE id = ?",
                    (str(row[0]),),
                ).fetchone()
                if existing is None:
                    raise EventStoreError("dedup index points to missing event")
                return self._row_to_event(existing)

        eid = event_id or str(uuid.uuid4())
        # Read prev_hash from DB inside the transaction to prevent stale cache
        # from forking the chain if another writer somehow got through.
        db_last = self.conn.execute("SELECT hash FROM events ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
        prev = str(db_last[0]) if db_last else self.GENESIS_PREV_HASH
        self._last_hash = prev  # sync cache
        hash_version = 2  # v2 includes contributor_id in the hash
        h = compute_event_hash(
            prev_hash=prev,
            event_type=event_type,
            payload=payload_canon,
            ts=now,
            source=source,
            trace_id=trace_id,
            schema_version=schema_version,
            dedupe_key=dedupe_key,
            event_id=eid,
            contributor_id=contributor_id,
            hash_version=hash_version,
        )

        try:
            self.conn.execute(
                """
                INSERT INTO events (
                    id, type, ts, observed_at, source, contributor_id, trace_id, schema_version, dedupe_key,
                    payload, prev_hash, hash, hash_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eid,
                    getattr(event_type, "value", str(event_type)),
                    _dt_to_iso(now),
                    _dt_to_iso(observed_at),
                    source,
                    contributor_id,
                    trace_id,
                    schema_version,
                    dedupe_key,
                    canonical_json(payload_canon),
                    prev,
                    h,
                    hash_version,
                ),
            )
            if dedupe_key is not None:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO event_dedup (dedupe_key, event_id, payload_hash, created_at)
                    VALUES (?, ?, ?, datetime('now'))
                    """,
                    (dedupe_key, eid, p_hash),
                )
                # Guard against race condition: another writer (e.g. `brain` fast-path)
                # may have inserted this dedupe_key between our early-check above and
                # the INSERT OR IGNORE.  If so, the IGNORE fired and the dedup row
                # belongs to a different event_id — undo our events row and return the
                # pre-existing event so the caller treats this as a successful no-op.
                dedup_row = self.conn.execute(
                    "SELECT event_id FROM event_dedup WHERE dedupe_key = ?",
                    (dedupe_key,),
                ).fetchone()
                if dedup_row is not None and str(dedup_row[0]) != eid:
                    import logging as _log

                    _log.getLogger("b1e55ed.database").debug(
                        "dedupe collision on concurrent insert — returning existing event: %s",
                        dedupe_key,
                    )
                    # Roll back the orphaned events row we just inserted.
                    # _last_hash is still `prev` at this point (not yet updated to h).
                    self.conn.execute("DELETE FROM events WHERE id = ?", (eid,))
                    existing_race = self.conn.execute(
                        "SELECT * FROM events WHERE id = ?",
                        (str(dedup_row[0]),),
                    ).fetchone()
                    if existing_race is None:
                        raise EventStoreError("dedup index points to missing event after race resolution")
                    return self._row_to_event(existing_race)
        except sqlite3.IntegrityError as e:
            raise EventStoreError(str(e)) from e

        self._last_hash = h
        return Event(
            id=eid,
            type=event_type,
            ts=now,
            observed_at=observed_at,
            source=source,
            trace_id=trace_id,
            schema_version=schema_version,
            dedupe_key=dedupe_key,
            payload=payload_canon,
            prev_hash=prev,
            hash=h,
        )

    def append_event(
        self,
        *,
        event_type: EventType,
        payload: dict[str, Any],
        event_id: str | None = None,
        observed_at: datetime | None = None,
        source: str | None = None,
        contributor_id: str | None = None,
        trace_id: str | None = None,
        schema_version: str = "v1",
        dedupe_key: str | None = None,
        ts: datetime | None = None,
        validate_ts: bool = True,
    ) -> Event:
        """Append a single event.

        Dedup semantics:
        - If dedupe_key is new: insert.
        - If dedupe_key exists with same payload_hash: idempotent (return existing event).
        - If dedupe_key exists with different payload_hash: conflict.

        validate_ts: if True and ts is not None, logs a warning when the event
        timestamp is more than 24 hours from wall clock (backdated or future-dated).
        Does not reject — producers may legitimately use historical timestamps.
        """

        if validate_ts and ts is not None:
            _ts = ts
            if _ts.tzinfo is None:
                _ts = _ts.replace(tzinfo=UTC)
            age = abs((datetime.now(tz=UTC) - _ts).total_seconds())
            if age > 86400:
                _logger.warning(
                    "Event ts is %.1f hours from now — may be backdated or future-dated (type=%s)",
                    age / 3600,
                    getattr(event_type, "value", str(event_type)),
                )

        with self._lock:
            # Use BEGIN EXCLUSIVE to prevent concurrent connections (other
            # processes sharing this WAL-mode database) from reading last_hash
            # between our read and insert — the default BEGIN DEFERRED only
            # acquires a shared lock on read, allowing two writers to fork
            # the hash chain.
            # Commit any implicit transaction from Python's sqlite3
            # auto-transaction (isolation_level="") before starting ours.
            self.conn.commit()
            self.conn.execute("BEGIN EXCLUSIVE")
            try:
                ev = self._append_event_inner(
                    event_type=event_type,
                    payload=payload,
                    event_id=event_id,
                    observed_at=observed_at,
                    source=source,
                    contributor_id=contributor_id,
                    trace_id=trace_id,
                    schema_version=schema_version,
                    dedupe_key=dedupe_key,
                    ts=ts,
                )
                # Periodic cleanup of stale api_rate_limits records (every 500 appends).
                # Runs inside the existing transaction to avoid an extra round-trip.
                self._cleanup_counter += 1
                if self._cleanup_counter >= 500:
                    self._cleanup_counter = 0
                    self.conn.execute("DELETE FROM api_rate_limits WHERE window_start < (strftime('%s', 'now') - 3600)")
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise

        # Side effects (best-effort): outbound webhooks.
        try:
            from engine.core.webhooks import dispatch_event_webhooks

            dispatch_event_webhooks(self, ev)
        except Exception:
            # Never break event persistence on webhook failure.
            pass

        return ev

    def append_events_batch(
        self,
        events: Iterable[tuple[EventType, dict[str, Any], str | None]],
        *,
        source: str | None = None,
    ) -> list[Event]:
        """Append a batch of events atomically.

        All events are inserted in a single transaction. If the process crashes
        mid-batch, no partial chain is written — it's all or nothing.

        Input tuples: (event_type, payload, dedupe_key)
        """

        event_list = list(events)
        if not event_list:
            return []

        out: list[Event] = []
        with self._lock:
            # Save state for rollback on failure.
            saved_hash = self._last_hash
            # Use BEGIN EXCLUSIVE so concurrent connections (other processes)
            # cannot read last_hash while we are building the batch chain.
            self.conn.commit()
            self.conn.execute("BEGIN EXCLUSIVE")
            try:
                for et, payload, dedupe_key in event_list:
                    ev = self._append_event_inner(
                        event_type=et,
                        payload=payload,
                        dedupe_key=dedupe_key,
                        source=source,
                    )
                    out.append(ev)
                self.conn.execute("COMMIT")
            except BaseException:
                # Restore cached hash on failure — the transaction rolled back.
                self._last_hash = saved_hash
                self.conn.execute("ROLLBACK")
                raise
        return out

    def prune_old_data(self, retention: Any) -> dict[str, int]:
        """Delete old records according to retention policy. Returns row counts deleted.

        ``retention`` is a ``RetentionConfig`` instance (imported lazily to avoid
        circular imports at module load time).

        VACUUM is executed *outside* the transaction because SQLite does not allow
        VACUUM inside an active transaction.
        """
        if not getattr(retention, "enabled", True):
            return {}

        deleted: dict[str, int] = {}
        with self._lock:
            self.conn.execute("BEGIN")
            try:
                # Events: keep last N days.
                # Bug fix: must delete from event_dedup (FK child) BEFORE events (FK parent)
                # to avoid FOREIGN KEY constraint violations when foreign_keys=ON.
                old_event_rows = self.conn.execute(
                    "SELECT id FROM events WHERE created_at < datetime('now', ?)",
                    (f"-{retention.events_keep_days} days",),
                ).fetchall()
                old_event_ids = [str(r[0]) for r in old_event_rows]
                if old_event_ids:
                    placeholders = ",".join("?" * len(old_event_ids))
                    self.conn.execute(
                        f"DELETE FROM event_dedup WHERE event_id IN ({placeholders})",
                        old_event_ids,
                    )
                    self.conn.execute(
                        f"DELETE FROM events WHERE id IN ({placeholders})",
                        old_event_ids,
                    )
                deleted["events"] = len(old_event_ids)

                # conviction_scores: only rows that have been resolved (outcome IS NOT NULL).
                # Bug fix: created_at column is added via migration in _init_schema();
                # referencing it here is now safe.
                cursor = self.conn.execute(
                    "DELETE FROM conviction_scores WHERE created_at < datetime('now', ?) AND outcome IS NOT NULL",
                    (f"-{retention.conviction_log_keep_days} days",),
                )
                deleted["conviction_scores"] = cursor.rowcount

                # feature_snapshots
                cursor = self.conn.execute(
                    "DELETE FROM feature_snapshots WHERE created_at < datetime('now', ?)",
                    (f"-{retention.feature_snapshots_keep_days} days",),
                )
                deleted["feature_snapshots"] = cursor.rowcount

                # api_rate_limits: window_start is an INTEGER epoch (seconds since Unix epoch).
                # Bug fix: old code compared integer epoch to datetime text, which always
                # evaluated as zero deleted rows.  Use strftime('%s','now') arithmetic instead.
                cursor = self.conn.execute(
                    "DELETE FROM api_rate_limits WHERE window_start < strftime('%s','now') - (? * 3600)",
                    (retention.api_rate_limits_keep_hours,),
                )
                deleted["api_rate_limits"] = cursor.rowcount

                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise

            # VACUUM must run outside the transaction block
            if getattr(retention, "vacuum_on_prune", True) and any(v > 0 for v in deleted.values()):
                self.conn.execute("VACUUM")

        return deleted

    def get_events(
        self,
        *,
        event_type: EventType | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        q = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if event_type is not None:
            q += " AND type = ?"
            params.append(getattr(event_type, "value", str(event_type)))
        if source is not None:
            q += " AND source = ?"
            params.append(source)
        if since is not None:
            q += " AND ts >= ?"
            params.append(_dt_to_iso(since))
        if until is not None:
            q += " AND ts <= ?"
            params.append(_dt_to_iso(until))
        q += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(q, tuple(params)).fetchall()
        return [self._row_to_event(r) for r in rows]

    def iter_events_ascending(
        self,
        *,
        from_id: str | None = None,
        to_id: str | None = None,
        event_type: EventType | None = None,
    ) -> list[Event]:
        """Return all events in chain order (ascending).

        Optional filters:
        - from_id / to_id: inclusive event ID range
        - event_type: filter by type
        """
        q = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if from_id is not None:
            q += " AND rowid >= (SELECT rowid FROM events WHERE id = ?)"
            params.append(from_id)
        if to_id is not None:
            q += " AND rowid <= (SELECT rowid FROM events WHERE id = ?)"
            params.append(to_id)
        if event_type is not None:
            q += " AND type = ?"
            params.append(getattr(event_type, "value", str(event_type)))
        q += " ORDER BY created_at ASC, rowid ASC"
        rows = self.conn.execute(q, tuple(params)).fetchall()
        return [self._row_to_event(r) for r in rows]

    def detect_concurrent_writers(self) -> bool:
        """Check if another process holds a write lock on the database.

        Returns True if a concurrent writer is detected (dangerous for hash chain).
        """
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute("ROLLBACK")
            return False
        except sqlite3.OperationalError:
            return True

    def verify_hash_chain(self, *, fast: bool = True, last_n: int = 1000) -> bool:
        """Verify the event hash chain.

        fast=True (default): verify only the last ``last_n`` events — safe with WAL
        mode because concurrent readers no longer block writers.
        fast=False: verify the entire chain (use for audits, not routine checks).
        """

        q = """
            SELECT id, type, payload, prev_hash, hash, ts, source, trace_id, schema_version,
                   dedupe_key, contributor_id, hash_version
            FROM events ORDER BY created_at ASC, rowid ASC
        """
        rows = self.conn.execute(q).fetchall()
        if fast and len(rows) > last_n:
            rows = rows[-last_n:]
            # For partial verification we trust the first row's prev_hash.
            prev = str(rows[0][3]) if rows[0][3] is not None else None
        else:
            prev = self.GENESIS_PREV_HASH

        for row in rows:
            et = EventType(str(row[1]))
            payload = json.loads(str(row[2]))
            ts = _iso_to_dt(str(row[5])) or datetime.now(tz=UTC)
            # hash_version may be NULL for legacy rows written before the column was added.
            hv_raw = row[11]
            hv = int(hv_raw) if hv_raw is not None else 1
            cid = row[10]  # contributor_id (may be None for v1 events)
            expected = compute_event_hash(
                prev_hash=prev,
                event_type=et,
                payload=payload,
                ts=ts,
                source=row[6],
                trace_id=row[7],
                schema_version=str(row[8]),
                dedupe_key=row[9],
                event_id=str(row[0]),
                contributor_id=cid,
                hash_version=hv,
            )
            if expected != str(row[4]):
                return False
            prev = expected
        return True

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        payload = json.loads(row["payload"])
        # hash_version may be absent in rows written before the column was added.
        try:
            hv = int(row["hash_version"]) if row["hash_version"] is not None else 1
        except (IndexError, KeyError):
            hv = 1
        return Event(
            id=str(row["id"]),
            type=EventType(str(row["type"])),
            ts=_iso_to_dt(str(row["ts"])) or datetime.now(tz=UTC),
            observed_at=_iso_to_dt(row["observed_at"]) if row["observed_at"] else None,
            source=row["source"],
            trace_id=row["trace_id"],
            schema_version=str(row["schema_version"]),
            dedupe_key=row["dedupe_key"],
            payload=payload,
            prev_hash=row["prev_hash"],
            hash=str(row["hash"]),
            hash_version=hv,
        )
