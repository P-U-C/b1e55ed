from __future__ import annotations

from datetime import UTC, datetime, timedelta

from engine.core.database import Database
from engine.integration.learning_loop import LearningLoopIntegration


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _seed(db: Database, *, pos_id: str, cycle_id: str, pnl: float, onchain: float, social: float, opened: datetime, closed: datetime):
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO conviction_scores (cycle_id, node_id, symbol, direction, magnitude, timeframe, ts, commitment_hash)
            VALUES (?, 'node', 'BTC', 'long', 5.0, '1d', ?, 'h')
            """,
            (cycle_id, _iso(opened)),
        )
        cid = int(db.conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        db.conn.execute(
            """
            INSERT INTO conviction_log (cycle_id, symbol, domain, domain_score, domain_weight, weighted_contribution, ts)
            VALUES (?, 'BTC', 'onchain', ?, 0.25, ?, ?)
            """,
            (cycle_id, float(onchain), float(onchain) * 0.25, _iso(opened)),
        )
        db.conn.execute(
            """
            INSERT INTO conviction_log (cycle_id, symbol, domain, domain_score, domain_weight, weighted_contribution, ts)
            VALUES (?, 'BTC', 'social', ?, 0.15, ?, ?)
            """,
            (cycle_id, float(social), float(social) * 0.15, _iso(opened)),
        )

        db.conn.execute(
            """
            INSERT INTO positions (id, platform, asset, direction, entry_price, size_notional, opened_at, closed_at, status, realized_pnl, conviction_id)
            VALUES (?, 'paper', 'BTC', 'long', 1.0, 1000.0, ?, ?, 'closed', ?, ?)
            """,
            (pos_id, _iso(opened), _iso(closed), float(pnl), cid),
        )


def test_learning_monthly_cycle_persists_weights(test_config, temp_dir):
    db = Database(temp_dir / "brain.db")

    now = datetime.now(tz=UTC)

    # Past cold start
    _seed(
        db,
        pos_id="pos-old",
        cycle_id="cycle-old",
        pnl=1.0,
        onchain=0.5,
        social=0.5,
        opened=now - timedelta(days=120),
        closed=now - timedelta(days=119),
    )

    # 20 trades in window with clear onchain alignment.
    opened = now - timedelta(days=10)
    closed = now - timedelta(days=9)
    for i in range(20):
        win = i % 2 == 0
        pnl = 10.0 if win else -10.0
        onchain = 0.9 if win else 0.1
        social = 0.1 if win else 0.9
        _seed(
            db,
            pos_id=f"pos-{i}",
            cycle_id=f"cycle-{i}",
            pnl=pnl,
            onchain=onchain,
            social=social,
            opened=opened,
            closed=closed,
        )

    integ = LearningLoopIntegration(db=db, config=test_config)
    summary = integ.run_monthly()

    # Learned weights file written
    learned_path = test_config.data_dir / "learned_weights.yaml"
    assert learned_path.exists()

    # DB history written
    rows = db.conn.execute("SELECT COUNT(*) AS n FROM learning_weights WHERE cycle_type = 'monthly'").fetchone()
    assert int(rows["n"]) > 0

    wa = summary["weight_adjustment"]
    assert wa["applied"] is True
