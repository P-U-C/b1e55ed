#!/usr/bin/env python3
"""Smoke tests for CI - verify basic functionality."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


def test_cli_help() -> None:
    """Verify CLI loads and help works."""
    import subprocess

    result = subprocess.run(
        ["uv", "run", "b1e55ed", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"CLI --help failed: {result.stderr}"
    assert "usage:" in result.stdout.lower(), "CLI help output malformed"
    print("✅ CLI help works")


def test_module_imports() -> None:
    """Verify all top-level modules import without errors."""
    modules = [
        "engine.core",
        "engine.brain",
        "engine.execution",
        "engine.producers",
        "engine.security",
        "engine.integration",
        "api",
        "dashboard",
    ]

    for mod in modules:
        try:
            __import__(mod)
            print(f"✅ {mod} imports")
        except Exception as e:
            print(f"❌ {mod} import failed: {e}", file=sys.stderr)
            raise


def test_database_schema() -> None:
    """Verify database schema loads."""
    from engine.core.database import Database

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path)

        # Check critical tables exist
        tables = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {r[0] for r in tables}

        required = {"events", "positions", "conviction_scores", "karma_intents"}
        missing = required - table_names
        assert not missing, f"Missing tables: {missing}"

        print(f"✅ Database schema valid ({len(table_names)} tables)")


def test_config_validation() -> None:
    """Verify config loads and validates."""
    from engine.core.config import Config

    # Test default config
    config = Config()
    assert config.preset in ["conservative", "balanced", "degen", "custom"]
    assert 0.0 <= config.weights.technical <= 1.0
    assert config.risk.max_drawdown_pct > 0

    print(f"✅ Config validation works (preset={config.preset})")


def main() -> int:
    """Run all smoke tests."""
    tests = [
        test_cli_help,
        test_module_imports,
        test_database_schema,
        test_config_validation,
    ]

    print("Running smoke tests...")
    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"\n❌ Smoke test failed: {test.__name__}", file=sys.stderr)
            print(f"   {e}", file=sys.stderr)
            return 1

    print("\n✅ All smoke tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
