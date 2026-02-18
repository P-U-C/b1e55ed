from __future__ import annotations

from datetime import UTC, datetime, timedelta

from engine.brain.learning import LearningLoop
from engine.core.database import Database


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def test_outcome_attribution_links_position_to_conviction(test_config, temp_dir):
    db = Database(temp_dir / "brain.db")

    # conviction score + conviction log
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO conviction_scores (cycle_id, node_id, symbol, direction, magnitude, timeframe, ts, commitment_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("cycle-1", "node", "BTC", "long", 5.0, "1d", _iso(datetime.now(tz=UTC)), "h"),
        )
        conviction_id = int(db.conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        db.conn.execute(
            """
            INSERT INTO conviction_log (cycle_id, symbol, domain, domain_score, domain_weight, weighted_contribution, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("cycle-1", "BTC", "onchain", 0.8, 0.25, 0.2, _iso(datetime.now(tz=UTC))),
        )

        opened = datetime.now(tz=UTC) - timedelta(hours=10)
        closed = datetime.now(tz=UTC)
        db.conn.execute(
            """
            INSERT INTO positions (id, platform, asset, direction, entry_price, size_notional, opened_at, closed_at, status,
                                  realized_pnl, conviction_id, regime_at_entry, max_drawdown_during)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'closed', ?, ?, ?, ?)
            """,
            (
                "pos-1",
                "paper",
                "BTC",
                "long",
                50000.0,
                1000.0,
                _iso(opened),
                _iso(closed),
                12.0,
                conviction_id,
                "BULL",
                -0.05,
            ),
        )

    loop = LearningLoop(db=db, config=test_config)
    attr = loop.attribute_outcome(position_id="pos-1", realized_pnl=12.0)

    assert attr.position_id == "pos-1"
    assert attr.conviction_id == conviction_id
    assert attr.direction_correct is True
    assert attr.time_held_hours > 0
    assert attr.regime_at_entry == "BULL"
    assert attr.domain_scores_at_entry["onchain"] == 0.8


def test_cold_start_blocks_weight_adjustment(test_config, temp_dir):
    db = Database(temp_dir / "brain.db")

    # Create >= MIN_OBSERVATIONS positions but within first 30 days => blocked
    now = datetime.now(tz=UTC)
    opened = now - timedelta(days=2)
    closed = now - timedelta(days=1)

    with db.conn:
        for i in range(25):
            db.conn.execute(
                """
                INSERT INTO conviction_scores (cycle_id, node_id, symbol, direction, magnitude, timeframe, ts, commitment_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (f"cycle-{i}", "node", "BTC", "long", 5.0, "1d", _iso(now), "h"),
            )
            conviction_id = int(db.conn.execute("SELECT last_insert_rowid()") .fetchone()[0])

            db.conn.execute(
                """
                INSERT INTO positions (id, platform, asset, direction, entry_price, size_notional, opened_at, closed_at, status,
                                      realized_pnl, conviction_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'closed', ?, ?)
                """,
                (
                    f"pos-{i}",
                    "paper",
                    "BTC",
                    "long",
                    50000.0,
                    1000.0,
                    _iso(opened),
                    _iso(closed),
                    10.0,
                    conviction_id,
                ),
            )

    loop = LearningLoop(db=db, config=test_config)
    wa = loop.adjust_domain_weights()
    assert wa.applied is False
    assert "cold_start" in wa.reason
