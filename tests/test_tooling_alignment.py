"""Wave 3 tooling alignment tests.

- test_prune_dry_run_api_rate_limits_uses_epoch_math
- test_dashboard_verify_chain_message_points_to_real_command
- test_verify_chain_command_registered
"""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("B1E55ED_INSECURE_OK", "1")
os.environ.setdefault("B1E55ED_DEV_MODE", "1")


# ---------------------------------------------------------------------------
# Test A: prune dry-run epoch math for api_rate_limits
# ---------------------------------------------------------------------------


def test_prune_dry_run_api_rate_limits_uses_epoch_math(tmp_path: Path) -> None:
    """Dry-run row count must match the real prune count for api_rate_limits."""
    from engine.core.config import RetentionConfig
    from engine.core.database import Database

    db_path = tmp_path / "brain.db"
    db = Database(str(db_path))

    keep_hours = 24
    old_epoch = int(time.time()) - (keep_hours + 2) * 3600  # 2 h beyond retention
    fresh_epoch = int(time.time()) - 1  # very recent — should NOT be deleted

    conn = db.conn
    conn.execute(
        "INSERT OR IGNORE INTO api_rate_limits (key, window_start, window_seconds, count) VALUES (?, ?, ?, ?)",
        ("test-key-old-1", old_epoch, 3600, 1),
    )
    conn.execute(
        "INSERT OR IGNORE INTO api_rate_limits (key, window_start, window_seconds, count) VALUES (?, ?, ?, ?)",
        ("test-key-old-2", old_epoch - 3600, 3600, 1),
    )
    conn.execute(
        "INSERT OR IGNORE INTO api_rate_limits (key, window_start, window_seconds, count) VALUES (?, ?, ?, ?)",
        ("test-key-fresh", fresh_epoch, 3600, 1),
    )
    conn.commit()

    # --- dry-run count (our fixed query) ---
    dry_count = (
        db.fetchone(
            "SELECT COUNT(*) FROM api_rate_limits WHERE window_start < strftime('%s','now') - (? * 3600)",
            (keep_hours,),
        )
        or (0,)
    )[0]

    # --- real prune count ---
    retention = RetentionConfig(api_rate_limits_keep_hours=keep_hours)
    deleted = db.prune_old_data(retention)
    real_count = deleted.get("api_rate_limits", 0)

    db.close()

    assert dry_count == real_count, f"dry-run reported {dry_count} rows but real prune deleted {real_count} rows"
    assert dry_count == 2, f"expected 2 old rows to be pruned, got {dry_count}"


# ---------------------------------------------------------------------------
# Test B: dashboard source references correct CLI command
# ---------------------------------------------------------------------------


def test_dashboard_verify_chain_message_points_to_real_command() -> None:
    """The dashboard verify-chain endpoint source must say 'b1e55ed verify-chain'."""
    # Read raw source file — avoids FastAPI module-level object issues
    dashboard_path = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
    source = dashboard_path.read_text()

    assert "b1e55ed verify-chain" in source, "Dashboard source must reference 'b1e55ed verify-chain'"
    assert "python -m engine verify-chain" not in source, "Dashboard source must NOT reference 'python -m engine verify-chain' (command does not exist)"


# ---------------------------------------------------------------------------
# Test C: verify-chain CLI command is registered in dispatch table
# ---------------------------------------------------------------------------


def test_verify_chain_command_registered() -> None:
    """'verify-chain' must appear in the CLI dispatch table and have an implementation."""
    import inspect

    import engine.cli.main as cli_mod

    # inspect.getsource on the module returns the full module source
    source = Path(inspect.getfile(cli_mod)).read_text()

    assert '"verify-chain": _cmd_verify_chain' in source, "'verify-chain' must be in the CLI dispatch table"
    assert "def _cmd_verify_chain" in source, "_cmd_verify_chain function must be defined"
