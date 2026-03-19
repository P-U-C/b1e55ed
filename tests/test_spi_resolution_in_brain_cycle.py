"""Test that SPI signal resolution runs inside the brain cycle."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.brain.orchestrator import BrainOrchestrator  # noqa: E402


def test_run_cycle_source_calls_resolve_expired_signals():
    """Verify the orchestrator source code invokes resolve_expired_signals."""
    source = inspect.getsource(BrainOrchestrator.run_cycle)
    assert "resolve_expired_signals" in source, "run_cycle must call resolve_expired_signals from engine.spi.resolution"
    # Wrapped in try/except so it never kills the cycle
    assert "except Exception" in source


def test_resolve_expired_signals_called_with_db(tmp_path):
    """Full run_cycle invokes resolve_expired_signals(self.db)."""
    from engine.brain.kill_switch import KillSwitchLevel
    from engine.core.config import Config
    from engine.core.database import Database

    db = Database(str(tmp_path / "test.db"))
    config = Config.from_repo_defaults(repo_root=ROOT)
    identity = MagicMock()
    identity.node_id = "test-node"

    orch = BrainOrchestrator(config=config, db=db, identity=identity)
    # Force kill switch level to CLEAR so cycle proceeds
    orch.kill_switch._level = KillSwitchLevel(0)

    mock_resolve = MagicMock(
        return_value=[
            SimpleNamespace(status="resolved"),
            SimpleNamespace(status="expired"),
        ]
    )
    with patch("engine.spi.resolution.resolve_expired_signals", mock_resolve):
        result = orch.run_cycle(symbols=["BTC"])

    mock_resolve.assert_called_once_with(db)
    assert result is not None


def test_run_cycle_survives_spi_resolution_failure(tmp_path):
    """If resolve_expired_signals raises, the cycle must still complete."""
    from engine.brain.kill_switch import KillSwitchLevel
    from engine.core.config import Config
    from engine.core.database import Database

    db = Database(str(tmp_path / "test.db"))
    config = Config.from_repo_defaults(repo_root=ROOT)
    identity = MagicMock()
    identity.node_id = "test-node"

    orch = BrainOrchestrator(config=config, db=db, identity=identity)
    orch.kill_switch._level = KillSwitchLevel(0)

    mock_resolve = MagicMock(side_effect=RuntimeError("db exploded"))
    with patch("engine.spi.resolution.resolve_expired_signals", mock_resolve):
        result = orch.run_cycle(symbols=["BTC"])

    # Cycle still completes
    assert result is not None
    assert result.cycle_id is not None
