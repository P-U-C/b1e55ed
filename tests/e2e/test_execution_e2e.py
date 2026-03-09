"""Execution E2E: signal → conviction → trade intent → OMS → paper fill → P&L tracking.

Verifies the full trade lifecycle end-to-end using an isolated temp DB.
Saves results to /tmp/execution_e2e_results.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure repo root on path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from engine.brain.kill_switch import KillSwitch  # noqa: E402
from engine.core.config import Config  # noqa: E402
from engine.core.database import Database  # noqa: E402
from engine.core.policy import TradingPolicy, TradingPolicyEngine  # noqa: E402
from engine.core.types import TradeIntent  # noqa: E402
from engine.execution.oms import OMS, default_sizer_from_config  # noqa: E402
from engine.execution.pnl import PnLTracker  # noqa: E402
from engine.execution.preflight import Preflight  # noqa: E402

# The test is the thesis. The results are the proof. The chain is the witness.
RESULTS: list[dict] = []


def _record(name: str, passed: bool, detail: str = ""):
    icon = "✅" if passed else "❌"
    print(f"  {icon} {name}" + (f" — {detail}" if detail else ""))
    RESULTS.append({"test": name, "passed": passed, "detail": detail})


def _setup(tmp: Path):
    """Create config + DB in a temp directory."""
    base = Config.from_repo_defaults(repo_root=REPO)
    cfg = base.model_copy(
        update={
            "data_dir": tmp / "data",
            "execution": base.execution.model_copy(update={"mode": "paper"}),
        }
    )
    db = Database(tmp / "db.sqlite")
    return cfg, db


def test_oms_state(cfg: Config, db: Database):
    """Check OMS can be instantiated and is in paper mode."""
    try:
        policy = TradingPolicyEngine(policy=TradingPolicy())
        ks = KillSwitch(db=db, config=cfg)
        pf = Preflight(policy=policy, kill_switch=ks)
        sizer = default_sizer_from_config(cfg)
        oms = OMS(config=cfg, db=db, preflight=pf, sizer=sizer, policy=policy)
        _record("OMS instantiation", True, f"mode={cfg.execution.mode}")
        return oms
    except Exception as e:
        _record("OMS instantiation", False, str(e))
        return None


def test_paper_mode_safe(cfg: Config):
    """Verify execution mode is paper (safe)."""
    mode = str(cfg.execution.mode)
    _record("Paper mode check", mode == "paper", f"mode={mode}")
    return mode == "paper"


def test_paper_trade(oms: OMS, db: Database):
    """Submit a paper trade and verify fill."""
    intent = TradeIntent(
        symbol="BTC",
        direction="long",
        size_pct=0.05,
        leverage=1.0,
        conviction_score=70.0,
        regime="trending_up",
        rationale="E2E test trade",
        stop_loss_pct=0.05,
        take_profit_pct=0.10,
    )
    result = oms.submit(
        intent,
        mid_price=100_000.0,
        equity_usd=10_000.0,
        portfolio_heat_pct=0.0,
        corr_to_portfolio=0.0,
    )
    filled = result.status == "filled"
    _record(
        "Paper trade submission",
        filled,
        f"status={result.status}, order={result.order_id}, pos={result.position_id}, "
        f"notional=${result.notional_usd}" + (f", reasons={result.reasons}" if result.reasons else ""),
    )
    return result


def test_position_recorded(db: Database, position_id: str | None):
    """Check position exists in DB."""
    if not position_id:
        _record("Position recorded", False, "no position_id")
        return False
    row = db.conn.execute(
        "SELECT id, asset, direction, entry_price, size_notional, status FROM positions WHERE id = ?",
        (position_id,),
    ).fetchone()
    if row:
        _record(
            "Position recorded",
            True,
            f"asset={row[1]}, dir={row[2]}, entry=${row[3]:.2f}, notional=${row[4]:.2f}, status={row[5]}",
        )
        return True
    _record("Position recorded", False, "not found in DB")
    return False


def test_order_recorded(db: Database, order_id: str | None):
    """Check order exists in orders table."""
    if not order_id:
        _record("Order recorded", False, "no order_id")
        return False
    row = db.conn.execute(
        "SELECT id, side, symbol, fill_price, status FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    if row:
        _record("Order recorded", True, f"side={row[1]}, symbol={row[2]}, fill=${row[3]:.2f}, status={row[4]}")
        return True
    _record("Order recorded", False, "not found in DB")
    return False


def test_events_emitted(db: Database):
    """Verify execution events were emitted."""
    counts = {}
    for t in [
        "execution.trade_intent.v1",
        "execution.order_submitted.v1",
        "execution.order_filled.v1",
        "execution.position_opened.v1",
    ]:
        c = db.conn.execute("SELECT count(*) FROM events WHERE type=?", (t,)).fetchone()[0]
        counts[t] = c
    all_present = all(v >= 1 for v in counts.values())
    _record("Execution events emitted", all_present, json.dumps(counts))
    return all_present


def test_pnl_unrealized(db: Database, cfg: Config, position_id: str | None):
    """Check unrealized P&L calculation."""
    if not position_id:
        _record("Unrealized P&L", False, "no position_id")
        return False
    tracker = PnLTracker(db=db, config=cfg)
    # Price went up 5% → long should profit
    upnl = tracker.unrealized_usd(position_id=position_id, mark_price=105_000.0)
    _record("Unrealized P&L (price +5%)", upnl > 0, f"${upnl:.2f}")
    return upnl > 0


def test_pnl_close(db: Database, cfg: Config, position_id: str | None):
    """Close position and verify realized P&L."""
    if not position_id:
        _record("Close + realized P&L", False, "no position_id")
        return False
    tracker = PnLTracker(db=db, config=cfg)
    try:
        rpnl = tracker.close_position(position_id=position_id, exit_price=105_000.0, reason="e2e_test")
        _record("Close + realized P&L", True, f"${rpnl:.2f}")
        # Verify status changed
        row = db.conn.execute("SELECT status, realized_pnl FROM positions WHERE id=?", (position_id,)).fetchone()
        _record("Position closed in DB", row and row[0] == "closed", f"status={row[0]}, pnl=${row[1]:.2f}" if row else "missing")
        return True
    except Exception as e:
        _record("Close + realized P&L", False, str(e))
        return False


def test_production_db_state():
    """Check the production DB for trade intent → execution flow."""
    prod_db = REPO / "data" / "brain.db"
    if not prod_db.exists():
        _record("Production DB check", False, "brain.db not found")
        return
    import sqlite3

    conn = sqlite3.connect(str(prod_db))
    conn.row_factory = sqlite3.Row

    intent_count = conn.execute("SELECT count(*) FROM events WHERE type='execution.trade_intent.v1'").fetchone()[0]
    order_count = conn.execute("SELECT count(*) FROM events WHERE type='execution.order_submitted.v1'").fetchone()[0]
    position_count = conn.execute("SELECT count(*) FROM positions").fetchone()[0]
    orders_count = conn.execute("SELECT count(*) FROM orders").fetchone()[0]

    _record(
        "Production DB: trade intents fired",
        intent_count > 0,
        f"{intent_count} intents, {order_count} orders submitted, {position_count} positions, {orders_count} order records",
    )

    # All 20 intents were rejected (0 orders) — investigate why
    if intent_count > 0 and order_count == 0:
        # Check kill switch state
        ks_events = conn.execute("SELECT count(*) FROM events WHERE type LIKE '%kill_switch%'").fetchone()[0]
        # Check recent rejection-related audit events
        audit = conn.execute("SELECT type, payload FROM events WHERE type LIKE '%audit%' OR type LIKE '%reject%' ORDER BY created_at DESC LIMIT 3").fetchall()
        detail = f"kill_switch_events={ks_events}"
        if audit:
            detail += f", recent_audits={[dict(r) for r in audit]}"
        _record("Production: intents→orders gap", False, f"All {intent_count} intents rejected. {detail}")
    conn.close()


def main():
    import tempfile

    print("\n🔬 Execution E2E Test Suite\n")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # 1. Setup
        print("\n📦 Setup")
        cfg, db = _setup(tmp_path)

        # 2. OMS state
        print("\n🏗️  OMS State")
        oms = test_oms_state(cfg, db)
        test_paper_mode_safe(cfg)

        if oms is None:
            print("\n⛔ Cannot continue without OMS")
            _save_results()
            return

        # 3. Paper trade
        print("\n📝 Paper Trade Execution")
        result = test_paper_trade(oms, db)

        # 4. Position + order recorded
        print("\n💾 Persistence")
        test_position_recorded(db, result.position_id if result.status == "filled" else None)
        test_order_recorded(db, result.order_id if result.status == "filled" else None)

        # 5. Events
        print("\n📡 Event Emission")
        test_events_emitted(db)

        # 6. P&L
        print("\n💰 P&L Tracking")
        pos_id = result.position_id if result.status == "filled" else None
        test_pnl_unrealized(db, cfg, pos_id)
        test_pnl_close(db, cfg, pos_id)

    # 7. Production DB
    print("\n🏭 Production DB State")
    test_production_db_state()

    # Summary
    _save_results()
    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("Failed:")
        for r in RESULTS:
            if not r["passed"]:
                print(f"  ❌ {r['test']}: {r['detail']}")


def _save_results():
    out = Path("/tmp/execution_e2e_results.json")
    out.write_text(json.dumps(RESULTS, indent=2))
    print(f"\n📄 Results saved to {out}")


if __name__ == "__main__":
    main()
