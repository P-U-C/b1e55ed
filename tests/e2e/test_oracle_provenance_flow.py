"""tests/e2e/test_oracle_provenance_flow.py

End-to-end tests for oracle provenance: direct engine calls (not via HTTP).

Tests
-----
1. Seed events from a known producer → has_provenance=True, total_signals > 0
2. Unknown producer → has_provenance=False
3. Query log written to file
4. Query log does NOT contain raw producer_id (anonymized)
5. Multiple producers tracked independently
6. Chain verified flag set correctly
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from engine.core.contributors import ContributorRegistry
from engine.core.database import Database
from engine.core.events import EventType
from engine.core.oracle_query_log import log_oracle_query
from engine.core.provenance import compute_provenance

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "brain.db")
    yield d
    d.close()


@pytest.fixture()
def data_dir(tmp_path) -> Path:
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_producer_events(db: Database, producer_id: str, count: int = 5) -> None:
    for i in range(count):
        db.append_event(
            event_type=EventType.SIGNAL_CURATOR_V1,
            payload={
                "symbol": "BTC",
                "direction": "bullish",
                "conviction": float(i + 1),
                "rationale": f"signal {i}",
                "source": producer_id,
            },
            source=producer_id,
        )


def _seed_conviction_scores(db: Database, node_id: str, count: int = 3) -> None:
    from datetime import datetime, timedelta

    try:
        from datetime import UTC  # py311+
    except ImportError:  # pragma: no cover
        from datetime import timezone as _tz  # noqa: PLC0415

        UTC = _tz.utc  # noqa: N806, UP017

    now = datetime.now(UTC)
    for i in range(count):
        ts = (now - timedelta(days=i)).isoformat()
        db.conn.execute(
            """
            INSERT INTO conviction_scores
            (node_id, symbol, direction, magnitude, timeframe, ts, commitment_hash, outcome, outcome_ts)
            VALUES (?, 'BTC', 'long', 5.0, '1h', ?, 'testhash', ?, ?)
            """,
            (node_id, ts, 1.0 if i % 2 == 0 else -0.05, ts),
        )
    db.conn.commit()


def _seed_contributor_mapped_signals(
    db: Database,
    *,
    node_id: str,
    name: str,
    source_alias: str,
    count: int = 2,
) -> None:
    reg = ContributorRegistry(db)
    contributor = reg.register(node_id=node_id, name=name, role="agent", metadata={})

    for i in range(count):
        db.append_event(
            event_type=EventType.SIGNAL_CURATOR_V1,
            payload={
                "symbol": "BTC",
                "direction": "bullish",
                "conviction": float(i + 1),
                "rationale": f"mapped signal {i}",
                "source": source_alias,
            },
            source=source_alias,
            contributor_id=contributor.id,
        )


# ---------------------------------------------------------------------------
# 1. Known producer → has_provenance=True, total_signals > 0
# ---------------------------------------------------------------------------


def test_known_producer_has_provenance(db):
    producer_id = "producer-known-001"
    _seed_producer_events(db, producer_id, count=5)

    result = compute_provenance(producer_id, db)

    assert result.producer_id == producer_id
    assert result.has_provenance is True
    assert result.chain_verified is True


def test_known_producer_total_signals_positive(db):
    """total_signals counts signal events for this producer identity."""
    producer_id = "producer-signals-001"
    _seed_producer_events(db, producer_id, count=3)
    _seed_conviction_scores(db, producer_id, count=4)

    result = compute_provenance(producer_id, db)

    assert result.has_provenance is True
    assert result.total_signals == 3, f"Expected 3 signal events, got {result.total_signals}"


def test_known_producer_first_last_seen(db):
    """first_seen and last_seen must be populated for a known producer."""
    producer_id = "producer-dates-001"
    _seed_producer_events(db, producer_id, count=3)

    result = compute_provenance(producer_id, db)

    assert result.first_seen is not None
    assert result.last_seen is not None


# ---------------------------------------------------------------------------
# 2. Unknown producer → has_provenance=False
# ---------------------------------------------------------------------------


def test_unknown_producer_no_provenance(db):
    result = compute_provenance("producer-does-not-exist-xyz", db)

    assert result.has_provenance is False
    assert result.total_signals == 0
    assert result.chain_verified is False
    assert result.first_seen is None
    assert result.last_seen is None
    assert "No provenance" in result.note


# ---------------------------------------------------------------------------
# 3. Query log written to file
# ---------------------------------------------------------------------------


def test_query_log_written(data_dir):
    log_oracle_query(
        producer_id="test-producer-log",
        signal_type="curator",
        has_provenance=True,
        data_dir=data_dir,
    )

    log_path = data_dir / "oracle_queries.jsonl"
    assert log_path.exists(), "oracle_queries.jsonl must be created"
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) >= 1

    record = json.loads(lines[-1])
    assert "ts" in record
    assert "producer_id_hash" in record
    assert "has_provenance" in record
    assert record["has_provenance"] is True


def test_query_log_appends_multiple_entries(data_dir):
    for i in range(3):
        log_oracle_query(
            producer_id=f"producer-{i}",
            signal_type="ta",
            has_provenance=i % 2 == 0,
            data_dir=data_dir,
        )

    log_path = data_dir / "oracle_queries.jsonl"
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 3


# ---------------------------------------------------------------------------
# 4. Query log does NOT contain raw producer_id (anonymized)
# ---------------------------------------------------------------------------


def test_query_log_anonymized(data_dir):
    """The raw producer_id must NEVER appear in the log — only its hash prefix."""
    raw_producer_id = "sensitive-producer-real-name-12345"

    log_oracle_query(
        producer_id=raw_producer_id,
        signal_type=None,
        has_provenance=False,
        data_dir=data_dir,
    )

    log_path = data_dir / "oracle_queries.jsonl"
    log_text = log_path.read_text()

    assert raw_producer_id not in log_text, "Raw producer_id must NEVER appear in the query log (privacy violation)"

    # Verify the hash prefix is correct
    expected_hash_prefix = hashlib.sha256(raw_producer_id.encode()).hexdigest()[:8]
    assert expected_hash_prefix in log_text, f"Expected hash prefix {expected_hash_prefix} not found in log"


def test_query_log_no_full_hash_in_log(data_dir):
    """Only the first 8 chars of the hash are stored, not the full hash."""
    raw_producer_id = "another-sensitive-producer"
    full_hash = hashlib.sha256(raw_producer_id.encode()).hexdigest()
    hash_suffix = full_hash[8:]  # the part after the prefix

    log_oracle_query(
        producer_id=raw_producer_id,
        signal_type="onchain",
        has_provenance=True,
        data_dir=data_dir,
    )

    log_path = data_dir / "oracle_queries.jsonl"
    log_text = log_path.read_text()

    # The suffix should not be in the log
    assert hash_suffix not in log_text, "Full hash must not be stored — only 8-char prefix"


# ---------------------------------------------------------------------------
# 5. Multiple producers tracked independently
# ---------------------------------------------------------------------------


def test_multiple_producers_independent(db):
    """Each producer has its own provenance record."""
    pid_a = "producer-multi-a"
    pid_b = "producer-multi-b"

    _seed_producer_events(db, pid_a, count=3)
    _seed_producer_events(db, pid_b, count=7)

    result_a = compute_provenance(pid_a, db)
    result_b = compute_provenance(pid_b, db)

    assert result_a.has_provenance is True
    assert result_b.has_provenance is True
    # Operator coverage counts are independent
    assert result_a.producer_id == pid_a
    assert result_b.producer_id == pid_b


def test_provenance_resolves_node_id_to_source_alias_events(db):
    """node_id lookups must include contributor-linked source aliases."""
    node_id = "node-provenance-001"
    _seed_contributor_mapped_signals(
        db,
        node_id=node_id,
        name="agent-provenance",
        source_alias="operator:telegram",
        count=2,
    )

    result = compute_provenance(node_id, db)

    assert result.has_provenance is True
    assert result.producer_id == node_id
    assert result.total_signals == 2
    assert result.operator_coverage == 1


def test_provenance_resolves_source_alias_to_canonical_node_id(db):
    """source alias lookups must resolve to the same canonical producer identity."""
    node_id = "node-provenance-002"
    source_alias = "agent-display-name"
    _seed_contributor_mapped_signals(
        db,
        node_id=node_id,
        name="Agent Display Name",
        source_alias=source_alias,
        count=3,
    )

    by_alias = compute_provenance(source_alias, db)
    by_node = compute_provenance(node_id, db)

    assert by_alias.has_provenance is True
    assert by_alias.producer_id == node_id
    assert by_alias.total_signals == by_node.total_signals == 3
    assert by_alias.operator_coverage == by_node.operator_coverage == 1


# ---------------------------------------------------------------------------
# 6. Attribution windows populated when conviction scores exist
# ---------------------------------------------------------------------------


def test_attribution_windows_populated(db):
    producer_id = "producer-windows-001"
    _seed_producer_events(db, producer_id, count=3)
    _seed_conviction_scores(db, producer_id, count=5)

    result = compute_provenance(producer_id, db)

    assert result.has_provenance is True
    # Should have at least one window (7d is most likely given recent data)
    assert len(result.attribution_windows) >= 1

    for key, window in result.attribution_windows.items():
        assert key in ("7d", "30d", "90d")
        assert window.signals >= 1
        assert isinstance(window.hit_rate, float)
        assert isinstance(window.max_drawdown_pct, float)


# ---------------------------------------------------------------------------
# 7. ProvenanceResult shape contract
# ---------------------------------------------------------------------------


def test_provenance_result_shape_known(db):
    """ProvenanceResult fields must all be present and correct types."""
    pid = "producer-shape-test"
    _seed_producer_events(db, pid, count=2)

    r = compute_provenance(pid, db)

    assert isinstance(r.producer_id, str)
    assert isinstance(r.has_provenance, bool)
    assert isinstance(r.chain_verified, bool)
    assert isinstance(r.total_signals, int)
    assert isinstance(r.p_and_l_attributed, bool)
    assert isinstance(r.operator_coverage, int)
    assert isinstance(r.note, str)
    assert isinstance(r.attribution_windows, dict)


def test_provenance_result_shape_unknown(db):
    """Unknown producer ProvenanceResult must still have correct types."""
    r = compute_provenance("ghost-producer-xyz", db)

    assert isinstance(r.producer_id, str)
    assert r.has_provenance is False
    assert isinstance(r.chain_verified, bool)
    assert r.total_signals == 0
    assert r.first_seen is None
    assert r.last_seen is None
