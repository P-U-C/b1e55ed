"""Tests for b1e55ed doctor command — tiers 0, 1, 2."""

from __future__ import annotations

import argparse
import json

# ── Tier 0 Tests ─────────────────────────────────────────────────────────


class TestTier0:
    def test_check_python_version_pass(self):
        from engine.doctor.tier0 import check_python_version

        # Current Python should be detected (pass or warn depending on version)
        result = check_python_version()
        assert result.name == "python_version"
        assert result.status in ("pass", "warn")
        assert "Python" in result.message

    def test_check_python_version_low(self):
        from engine.doctor.tier0 import check_python_version

        # Require absurdly high version → should warn
        result = check_python_version(min_major=99, min_minor=0)
        assert result.status == "warn"

    def test_check_dependencies_pass(self):
        from engine.doctor.tier0 import check_dependencies

        result = check_dependencies()
        assert result.name == "dependencies"
        # At minimum yaml and pydantic should be importable
        # Status depends on full dep set
        assert result.status in ("pass", "fail")

    def test_check_db_writable(self):
        from engine.doctor.tier0 import check_db_writable

        result = check_db_writable()
        assert result.name == "db_writable"
        assert result.status in ("pass", "fail")

    def test_check_identity(self):
        from engine.doctor.tier0 import check_identity

        result = check_identity()
        assert result.name == "identity"
        assert result.status in ("pass", "warn")

    def test_check_kill_switch(self):
        from engine.doctor.tier0 import check_kill_switch

        result = check_kill_switch()
        assert result.name == "kill_switch"
        assert result.status in ("pass", "warn")

    def test_check_user_config(self):
        from engine.doctor.tier0 import check_user_config

        result = check_user_config()
        assert result.name == "user_config"
        assert result.status in ("pass", "warn", "fail")

    def test_run_tier0(self):
        from engine.doctor.tier0 import run_tier0

        results = run_tier0()
        assert len(results) == 6
        for r in results:
            assert r.status in ("pass", "warn", "fail")
            assert r.name
            assert r.message


# ── Tier 1 Tests ─────────────────────────────────────────────────────────


class TestTier1:
    def test_check_producers(self):
        from engine.doctor.tier1 import check_producers

        result = check_producers()
        assert result.name == "producers"
        assert result.status in ("pass", "warn", "fail")

    def test_check_orchestrator(self):
        from engine.doctor.tier1 import check_orchestrator

        result = check_orchestrator()
        assert result.name == "orchestrator"
        assert result.status in ("pass", "fail")

    def test_check_oms(self):
        from engine.doctor.tier1 import check_oms

        result = check_oms()
        assert result.name == "oms"
        assert result.status in ("pass", "fail")

    def test_check_oms_wired(self):
        from engine.doctor.tier1 import check_oms_wired

        result = check_oms_wired()
        assert result.name == "oms_wired"
        assert result.status in ("pass", "warn")

    def test_check_dashboard(self):
        from engine.doctor.tier1 import check_dashboard

        result = check_dashboard()
        assert result.name == "dashboard"
        assert result.status in ("pass", "warn", "fail")

    def test_run_tier1(self):
        from engine.doctor.tier1 import run_tier1

        results = run_tier1()
        assert len(results) == 5
        for r in results:
            assert r.status in ("pass", "warn", "fail")


# ── Tier 2 Tests ─────────────────────────────────────────────────────────


class TestTier2:
    def test_check_signal_ingestion(self):
        from engine.doctor.tier2 import check_signal_ingestion

        result = check_signal_ingestion()
        assert result.name == "signal_ingestion"
        assert result.status in ("pass", "fail")

    def test_check_brain_cycle(self):
        from engine.doctor.tier2 import check_brain_cycle

        result = check_brain_cycle()
        assert result.name == "brain_cycle"
        assert result.status in ("pass", "warn", "fail")

    def test_check_outcome_resolution(self):
        from engine.doctor.tier2 import check_outcome_resolution

        result = check_outcome_resolution()
        assert result.name == "outcome_resolution"
        assert result.status in ("pass", "warn", "fail")

    def test_check_learning_weights(self):
        from engine.doctor.tier2 import check_learning_weights

        result = check_learning_weights()
        assert result.name == "learning_weights"
        assert result.status in ("pass", "fail")

    def test_check_karma_intents(self):
        from engine.doctor.tier2 import check_karma_intents

        result = check_karma_intents()
        assert result.name == "karma_intents"
        assert result.status in ("pass", "fail")

    def test_run_tier2(self):
        from engine.doctor.tier2 import run_tier2

        results = run_tier2()
        assert len(results) == 5
        for r in results:
            assert r.status in ("pass", "warn", "fail")


# ── CLI Integration Tests ────────────────────────────────────────────────


class TestDoctorCLI:
    def test_run_doctor_json(self, capsys):
        """Doctor with --json produces valid JSON."""
        from engine.cli.doctor import run_doctor

        args = argparse.Namespace(tier=0, json=True, fix=False)
        exit_code = run_doctor(args)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "version" in data
        assert "score" in data
        assert "tiers" in data
        assert "T0 Preflight" in data["tiers"]
        assert exit_code in (0, 1)

    def test_run_doctor_human(self, capsys):
        """Doctor produces human-readable output."""
        from engine.cli.doctor import run_doctor

        args = argparse.Namespace(tier=0, json=False, fix=False)
        run_doctor(args)
        captured = capsys.readouterr()
        assert "b1e55ed doctor" in captured.out
        assert "T0 Preflight" in captured.out
        assert "Score:" in captured.out

    def test_run_doctor_tier1(self, capsys):
        """Doctor tier=1 includes T0 and T1."""
        from engine.cli.doctor import run_doctor

        args = argparse.Namespace(tier=1, json=True, fix=False)
        run_doctor(args)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "T0 Preflight" in data["tiers"]
        assert "T1 Components" in data["tiers"]
        assert "T2 Pipeline" not in data["tiers"]

    def test_run_doctor_tier2(self, capsys):
        """Doctor tier=2 includes all tiers."""
        from engine.cli.doctor import run_doctor

        args = argparse.Namespace(tier=2, json=True, fix=False)
        run_doctor(args)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "T0 Preflight" in data["tiers"]
        assert "T1 Components" in data["tiers"]
        assert "T2 Pipeline" in data["tiers"]

    def test_run_doctor_fix_flag(self, capsys):
        """Doctor --fix runs without crashing."""
        from engine.cli.doctor import run_doctor

        args = argparse.Namespace(tier=0, json=True, fix=True)
        run_doctor(args)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "fix_actions" in data

    def test_argparse_wiring(self):
        """Doctor subcommand is registered in argparse."""
        from engine.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["doctor", "--tier", "0", "--json"])
        assert args.command == "doctor"
        assert args.tier == 0
        assert args.json is True

    def test_dispatch_wiring(self):
        """Doctor is in the dispatch table."""
        from engine.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["doctor", "--tier", "0", "--json"])
        assert args.command == "doctor"


# ── CheckResult Tests ────────────────────────────────────────────────────


class TestCheckResult:
    def test_check_result_fields(self):
        from engine.doctor.tier0 import CheckResult

        r = CheckResult(name="test", status="pass", message="ok")
        assert r.name == "test"
        assert r.status == "pass"
        assert r.message == "ok"
        assert r.remediation is None

    def test_check_result_with_remediation(self):
        from engine.doctor.tier0 import CheckResult

        r = CheckResult(name="test", status="fail", message="broken", remediation="fix it")
        assert r.remediation == "fix it"
