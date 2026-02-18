from __future__ import annotations

from datetime import UTC, datetime, timedelta

from engine.brain.learning import LearningLoop
from engine.core.database import Database


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _seed_position(
    *,
    db: Database,
    position_id: str,
    cycle_id: str,
    symbol: str,
    realized_pnl: float,
    domain_scores: dict[str, float],
    opened_at: datetime,
    closed_at: datetime,
) -> None:
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO conviction_scores (cycle_id, node_id, symbol, direction, magnitude, timeframe, ts, commitment_hash)
            VALUES (?, ?, ?, 'long', 5.0, '1d', ?, 'h')
            """,
            (cycle_id, "node", symbol, _iso(opened_at)),
        )
        conviction_id = int(db.conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        for domain, score in domain_scores.items():
            db.conn.execute(
                """
                INSERT INTO conviction_log (cycle_id, symbol, domain, domain_score, domain_weight, weighted_contribution, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (cycle_id, symbol, domain, float(score), 0.1, float(score) * 0.1, _iso(opened_at)),
            )

        db.conn.execute(
            """
            INSERT INTO positions (
                id, platform, asset, direction, entry_price, size_notional, opened_at, closed_at, status, realized_pnl, conviction_id
            ) VALUES (?, 'paper', ?, 'long', 1.0, 1000.0, ?, ?, 'closed', ?, ?)
            """,
            (position_id, symbol, _iso(opened_at), _iso(closed_at), float(realized_pnl), conviction_id),
        )


def test_weight_nudges_toward_better_domain(test_config, temp_dir):
    db = Database(temp_dir / "brain.db")

    # Ensure we are past cold-start by setting first closed >90d ago.
    now = datetime.now(tz=UTC)
    base_open = now - timedelta(days=120)
    base_close = now - timedelta(days=119)

    # Seed one old closed trade so age_days >= 90.
    _seed_position(
        db=db,
        position_id="pos-old",
        cycle_id="cycle-old",
        symbol="BTC",
        realized_pnl=1.0,
        domain_scores={"onchain": 0.5, "social": 0.5},
        opened_at=base_open,
        closed_at=base_close,
    )

    # Create 20 observations in last 30d.
    opened = now - timedelta(days=10)
    closed = now - timedelta(days=9)

    for i in range(20):
        # onchain aligns with wins: high score on wins, low on losses
        win = i % 2 == 0
        pnl = 10.0 if win else -10.0
        onchain = 0.9 if win else 0.1
        social = 0.1 if win else 0.9

        _seed_position(
            db=db,
            position_id=f"pos-{i}",
            cycle_id=f"cycle-{i}",
            symbol="BTC",
            realized_pnl=pnl,
            domain_scores={"onchain": onchain, "social": social},
            opened_at=opened,
            closed_at=closed,
        )

    loop = LearningLoop(db=db, config=test_config)
    wa = loop.adjust_domain_weights()

    assert wa.applied is True
    assert wa.reason in {"adjusted", "reverted"}

    # onchain should not lose weight relative to social with this setup.
    assert wa.new_weights["onchain"] >= wa.previous_weights["onchain"]
    assert wa.new_weights["social"] <= wa.previous_weights["social"]

    # Bounds enforced
    assert all(loop.MIN_DOMAIN_WEIGHT <= w <= loop.MAX_DOMAIN_WEIGHT for w in wa.new_weights.values())
    assert abs(sum(wa.new_weights.values()) - 1.0) < 1e-6


def test_insufficient_data_no_change(test_config, temp_dir):
    db = Database(temp_dir / "brain.db")

    now = datetime.now(tz=UTC)
    # Past cold start
    _seed_position(
        db=db,
        position_id="pos-old",
        cycle_id="cycle-old",
        symbol="BTC",
        realized_pnl=1.0,
        domain_scores={"onchain": 0.5},
        opened_at=now - timedelta(days=120),
        closed_at=now - timedelta(days=119),
    )

    # Only 5 observations
    for i in range(5):
        _seed_position(
            db=db,
            position_id=f"pos-{i}",
            cycle_id=f"cycle-{i}",
            symbol="BTC",
            realized_pnl=1.0,
            domain_scores={"onchain": 0.8},
            opened_at=now - timedelta(days=10),
            closed_at=now - timedelta(days=9),
        )

    loop = LearningLoop(db=db, config=test_config)
    wa = loop.adjust_domain_weights()
    assert wa.applied is False
    assert wa.reason == "insufficient_data"
    assert wa.new_weights == wa.previous_weights
