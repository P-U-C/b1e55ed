"""Tests for Issue 4 (reconcile parser) and Issue 5 (setup repair kill-switch query)."""

from __future__ import annotations

import subprocess
import sys


def test_reconcile_parser_registered():
    """reconcile subparser must be registered so `b1e55ed reconcile --help` exits 0."""
    result = subprocess.run(
        [sys.executable, "-m", "engine.cli", "reconcile", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Expected exit 0 from `reconcile --help`, got {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "reconcile" in result.stdout.lower() or "backfill" in result.stdout.lower(), (
        f"Expected 'reconcile' or 'backfill' in help output, got:\n{result.stdout}"
    )


def test_repair_uses_canonical_kill_switch_type():
    """setup repair must use EventType.KILL_SWITCH_V1.value, not the hardcoded wrong string."""
    from engine.core.events import EventType

    canonical = EventType.KILL_SWITCH_V1.value  # "system.kill_switch.v1"

    # Read the source file and verify the correct value is used
    from pathlib import Path

    setup_src = (Path(__file__).resolve().parents[2] / "engine" / "cli" / "commands" / "setup.py").read_text()

    # The hardcoded wrong string must be gone
    assert "= 'KILL_SWITCH_V1'" not in setup_src, "setup.py still uses hardcoded 'KILL_SWITCH_V1' string — must use EventType.KILL_SWITCH_V1.value"
    # The code must reference the enum value dynamically
    assert "EventType.KILL_SWITCH_V1.value" in setup_src, (
        f"setup.py must use EventType.KILL_SWITCH_V1.value (canonical: '{canonical}') instead of hardcoded string"
    )
