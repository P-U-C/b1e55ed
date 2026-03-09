"""Tests for engine.doctor tiers 3 and 4.

Tier 3 uses mocks for live HTTP endpoints.
Tier 4 uses real temp DB but is self-contained (no network).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

# ─── Tier 3 Tests ───────────────────────────────────────────────────────


class TestTier3:
    """Tier 3 live checks with mocked HTTP."""

    def test_api_health_pass(self):
        from engine.doctor.tier3 import check_api_health

        with patch("engine.doctor.tier3._http_get", return_value=(200, '{"status":"ok"}')):
            r = check_api_health("http://localhost:5050")
            assert r.status == "pass"
            assert "200" in r.message

    def test_api_health_fail(self):
        from engine.doctor.tier3 import check_api_health

        with patch("engine.doctor.tier3._http_get", return_value=(0, "Connection refused")):
            r = check_api_health("http://localhost:5050")
            assert r.status == "fail"
            assert "unreachable" in r.message.lower()

    def test_api_health_non_200(self):
        from engine.doctor.tier3 import check_api_health

        with patch("engine.doctor.tier3._http_get", return_value=(500, "Internal Server Error")):
            r = check_api_health("http://localhost:5050")
            assert r.status == "warn"

    def test_api_auth_pass(self):
        from engine.doctor.tier3 import check_api_auth

        with patch("engine.doctor.tier3._http_get", return_value=(200, '{"status":"ok"}')):
            r = check_api_auth("http://localhost:5050", "test-token-123")
            assert r.status == "pass"

    def test_api_auth_rejected(self):
        from engine.doctor.tier3 import check_api_auth

        with patch("engine.doctor.tier3._http_get", return_value=(401, "Unauthorized")):
            r = check_api_auth("http://localhost:5050", "bad-token")
            assert r.status == "fail"

    def test_api_auth_no_token(self):
        from engine.doctor.tier3 import check_api_auth

        r = check_api_auth("http://localhost:5050", None)
        assert r.status == "warn"
        assert "no auth token" in r.message.lower()

    def test_dashboard_pass(self):
        from engine.doctor.tier3 import check_dashboard

        with patch("engine.doctor.tier3._http_get", return_value=(200, "<html>")):
            r = check_dashboard("http://localhost:5051")
            assert r.status == "pass"

    def test_dashboard_fail(self):
        from engine.doctor.tier3 import check_dashboard

        with patch("engine.doctor.tier3._http_get", return_value=(0, "Connection refused")):
            r = check_dashboard("http://localhost:5051")
            assert r.status == "fail"

    def test_kill_switch_live_no_db(self):
        from engine.doctor.tier3 import check_kill_switch_live

        r = check_kill_switch_live(db_path=Path("/nonexistent/brain.db"))
        assert r.status == "warn"

    def test_kill_switch_live_safe(self):
        """Kill switch is safe when no events exist."""
        from engine.core.database import Database
        from engine.doctor.tier3 import check_kill_switch_live

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.close()
            r = check_kill_switch_live(db_path=db_path)
            assert r.status == "pass"
            assert "safe" in r.message.lower() or "l0" in r.message.lower()

    def test_last_brain_cycle_no_events(self):
        from engine.core.database import Database
        from engine.doctor.tier3 import check_last_brain_cycle

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.close()
            r = check_last_brain_cycle(db_path=db_path)
            assert r.status == "warn"

    def test_producer_health_no_producers(self):
        from engine.core.database import Database
        from engine.doctor.tier3 import check_producer_health

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.close()
            r = check_producer_health(db_path=db_path)
            assert r.status == "warn"

    def test_intent_to_order_no_intents(self):
        from engine.core.database import Database
        from engine.doctor.tier3 import check_intent_to_order

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.close()
            r = check_intent_to_order(db_path=db_path)
            assert r.status == "warn"

    def test_run_tier3_returns_all_checks(self):
        """run_tier3 returns 7 check results."""
        from engine.doctor.tier3 import run_tier3

        with patch("engine.doctor.tier3._http_get", return_value=(0, "mocked")):
            results = run_tier3(api_port=9999, dashboard_port=9998)
            assert len(results) == 7
            assert all(hasattr(r, "status") for r in results)


# ─── Tier 4 Tests ───────────────────────────────────────────────────────


class TestTier4:
    """Tier 4 integration flywheel tests — self-contained, no network."""

    def test_create_temp_db(self):
        import shutil

        from engine.doctor.tier4 import check_create_temp_db

        check, db_path = check_create_temp_db()
        assert check.status == "pass"
        assert db_path is not None
        assert db_path.exists()
        shutil.rmtree(db_path.parent, ignore_errors=True)

    def test_wire_oms(self):
        import shutil

        from engine.doctor.tier4 import check_create_temp_db, check_wire_oms

        _, db_path = check_create_temp_db()
        assert db_path is not None
        try:
            r = check_wire_oms(db_path)
            assert r.status == "pass"
        finally:
            shutil.rmtree(db_path.parent, ignore_errors=True)

    def test_seed_signals(self):
        import shutil

        from engine.doctor.tier4 import check_create_temp_db, check_seed_signals

        _, db_path = check_create_temp_db()
        assert db_path is not None
        try:
            r = check_seed_signals(db_path)
            assert r.status == "pass"
            assert "5 signals" in r.message
        finally:
            shutil.rmtree(db_path.parent, ignore_errors=True)

    def test_brain_cycle(self):
        import shutil

        from engine.doctor.tier4 import (
            check_brain_cycle,
            check_create_temp_db,
            check_seed_signals,
        )

        _, db_path = check_create_temp_db()
        assert db_path is not None
        try:
            check_seed_signals(db_path)
            r = check_brain_cycle(db_path)
            assert r.status == "pass"
            assert "cycle" in r.message.lower() or "Cycle" in r.message
        finally:
            shutil.rmtree(db_path.parent, ignore_errors=True)

    def test_paper_trades(self):
        import shutil

        from engine.doctor.tier4 import (
            check_brain_cycle,
            check_create_temp_db,
            check_paper_trades,
            check_seed_signals,
        )

        _, db_path = check_create_temp_db()
        assert db_path is not None
        try:
            check_seed_signals(db_path)
            check_brain_cycle(db_path)
            r = check_paper_trades(db_path)
            # Should pass or warn (policy may block)
            assert r.status in ("pass", "warn")
        finally:
            shutil.rmtree(db_path.parent, ignore_errors=True)

    def test_resolve_outcomes(self):
        import shutil

        from engine.doctor.tier4 import (
            check_brain_cycle,
            check_create_temp_db,
            check_paper_trades,
            check_resolve_outcomes,
            check_seed_signals,
        )

        _, db_path = check_create_temp_db()
        assert db_path is not None
        try:
            check_seed_signals(db_path)
            check_brain_cycle(db_path)
            check_paper_trades(db_path)
            r = check_resolve_outcomes(db_path)
            assert r.status == "pass"
        finally:
            shutil.rmtree(db_path.parent, ignore_errors=True)

    def test_karma_intents(self):
        import shutil

        from engine.doctor.tier4 import (
            check_brain_cycle,
            check_create_temp_db,
            check_karma_intents,
            check_paper_trades,
            check_resolve_outcomes,
            check_seed_signals,
        )

        _, db_path = check_create_temp_db()
        assert db_path is not None
        try:
            check_seed_signals(db_path)
            check_brain_cycle(db_path)
            check_paper_trades(db_path)
            check_resolve_outcomes(db_path)
            r = check_karma_intents(db_path)
            # warn is acceptable (karma requires treasury_address)
            assert r.status in ("pass", "warn")
        finally:
            shutil.rmtree(db_path.parent, ignore_errors=True)

    def test_learning_loop(self):
        import shutil

        from engine.doctor.tier4 import (
            check_brain_cycle,
            check_create_temp_db,
            check_learning_loop,
            check_paper_trades,
            check_resolve_outcomes,
            check_seed_signals,
        )

        _, db_path = check_create_temp_db()
        assert db_path is not None
        try:
            check_seed_signals(db_path)
            check_brain_cycle(db_path)
            check_paper_trades(db_path)
            check_resolve_outcomes(db_path)
            r = check_learning_loop(db_path)
            assert r.status == "pass"
            assert "events" in r.message
        finally:
            shutil.rmtree(db_path.parent, ignore_errors=True)

    def test_full_flywheel(self):
        """End-to-end: run_tier4() completes all 8 checks."""
        from engine.doctor.tier4 import run_tier4

        results = run_tier4()
        assert len(results) == 8
        # All should pass or warn (never fail in clean environment)
        statuses = {r.status for r in results}
        assert "fail" not in statuses, f"Unexpected failures: {[(r.name, r.message) for r in results if r.status == 'fail']}"


# ─── CLI Integration Tests ──────────────────────────────────────────────


class TestDoctorCLI:
    """Test the CLI dispatches correctly."""

    def test_run_doctor_tier0_json(self):
        """run_doctor with tier=0, json=True returns valid JSON."""
        import argparse
        from io import StringIO

        from engine.cli.doctor import run_doctor

        args = argparse.Namespace(tier=0, json=True, fix=False, api_port=5050, dashboard_port=5051, auth_token=None)
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            run_doctor(args)

        import json

        output = mock_out.getvalue()
        data = json.loads(output)
        assert "score" in data
        assert "tiers" in data
        assert data["tier"] == 0

    def test_build_doctor_parser(self):
        """build_doctor_parser registers the subcommand."""
        import argparse

        from engine.cli.doctor import build_doctor_parser

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        build_doctor_parser(sub)

        args = parser.parse_args(["doctor", "--tier", "4", "--json"])
        assert args.tier == 4
        assert args.json is True
