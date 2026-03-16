"""Tests for identity-gate exemption of maintenance/recovery commands.

Operational commands (doctor, health, integrity, etc.) must run even when no
identity has been configured. An operator with a broken identity needs these
commands to diagnose and recover — blocking them creates an unsolvable catch-22.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest


def _no_identity_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up a clean HOME with no identity file and return the home dir."""
    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home_dir))
    # Ensure no identity.json exists
    identity_file = home_dir / ".b1e55ed" / "identity.json"
    assert not identity_file.exists(), "Test isolation broken: identity file found"
    return home_dir


class TestDoctorRunsWithoutIdentity:
    """b1e55ed doctor must run (not return IDENTITY_REQUIRED) without identity."""

    def test_doctor_runs_without_identity(self, tmp_path, monkeypatch, capsys):
        """Invoke run_doctor with no identity configured — must return output, not block."""
        _no_identity_home(tmp_path, monkeypatch)

        from engine.cli.doctor import run_doctor

        args = argparse.Namespace(tier=0, json=False, fix=False, api_port=5050, dashboard_port=5051, auth_token=None)
        rc = run_doctor(args)

        out = capsys.readouterr().out

        # Must not return an IDENTITY_REQUIRED error
        assert "IDENTITY_REQUIRED" not in out
        assert "Identity required" not in out

        # Must produce diagnostic output
        assert len(out) > 0

        # Return code: 0 (all pass) or 1 (some failures/warns) — both are valid
        assert rc in (0, 1)

    def test_doctor_json_runs_without_identity(self, tmp_path, monkeypatch, capsys):
        """doctor --json must produce valid JSON without identity."""
        _no_identity_home(tmp_path, monkeypatch)

        from engine.cli.doctor import run_doctor

        args = argparse.Namespace(tier=0, json=True, fix=False, api_port=5050, dashboard_port=5051, auth_token=None)
        run_doctor(args)

        out = capsys.readouterr().out
        data = json.loads(out)

        # Must not be an error response
        assert "error" not in data or data.get("error", {}).get("code") != "IDENTITY_REQUIRED"

        # Must have diagnostic structure
        assert "checks" in data or "results" in data or "summary" in data or "tiers" in data or "T0 Preflight" in str(data)


class TestHealthRunsWithoutIdentity:
    """b1e55ed health must run (not return IDENTITY_REQUIRED) without identity."""

    def test_health_runs_without_identity(self, tmp_path, monkeypatch, capsys):
        """Invoke _cmd_health with no identity configured — must produce health payload."""
        _no_identity_home(tmp_path, monkeypatch)

        from engine.cli.main import CliContext, _cmd_health  # type: ignore[attr-defined]

        # Scaffold minimal repo structure
        (tmp_path / "config").mkdir(parents=True, exist_ok=True)
        src_config = Path(__file__).resolve().parents[2] / "config" / "default.yaml"
        import shutil

        shutil.copy2(src_config, tmp_path / "config" / "default.yaml")

        ctx = CliContext(repo_root=tmp_path)
        args = argparse.Namespace(json=False)
        _cmd_health(ctx, args)

        out = capsys.readouterr().out

        # Must not return IDENTITY_REQUIRED
        assert "IDENTITY_REQUIRED" not in out
        assert "Identity required" not in out

        # Must produce some output
        assert len(out) > 0

    def test_health_json_runs_without_identity(self, tmp_path, monkeypatch, capsys):
        """health --json must produce a parseable JSON payload without identity."""
        _no_identity_home(tmp_path, monkeypatch)

        from engine.cli.main import CliContext, _cmd_health  # type: ignore[attr-defined]

        (tmp_path / "config").mkdir(parents=True, exist_ok=True)
        src_config = Path(__file__).resolve().parents[2] / "config" / "default.yaml"
        import shutil

        shutil.copy2(src_config, tmp_path / "config" / "default.yaml")

        ctx = CliContext(repo_root=tmp_path)
        args = argparse.Namespace(json=True)
        _cmd_health(ctx, args)

        out = capsys.readouterr().out
        data = json.loads(out)

        # Must not be an IDENTITY_REQUIRED error
        assert data.get("error", {}).get("code") != "IDENTITY_REQUIRED"

        # Must be a health payload with expected structure
        assert "ok" in data


class TestIdentityGateExemptList:
    """Verify the identity_gate_exempt set is defined and contains expected commands."""

    def test_exempt_set_contains_operational_commands(self):
        """The allowlist must include the commands operators need for recovery."""
        import ast
        import re

        source = Path(__file__).resolve().parents[2] / "engine" / "cli" / "main.py"
        text = source.read_text()

        # Match the full set literal on a single line: identity_gate_exempt = {...}
        match = re.search(r"identity_gate_exempt\s*=\s*(\{[^}]+\})", text)
        assert match is not None, "identity_gate_exempt not found in engine/cli/main.py"

        exempt = ast.literal_eval(match.group(1))

        expected = {"health", "doctor", "integrity", "verify-chain", "replay", "prune", "reconcile", "repair"}
        for cmd in expected:
            assert cmd in exempt, f"'{cmd}' missing from identity_gate_exempt"

    def test_exempt_commands_bypass_gate_in_main(self, tmp_path, monkeypatch, capsys):
        """main() must not return IDENTITY_REQUIRED for health when no identity is set."""
        _no_identity_home(tmp_path, monkeypatch)

        import unittest.mock as mock

        with (
            mock.patch("engine.core.identity_gate.is_dev_mode", return_value=False),
            mock.patch("engine.core.identity_gate.load_identity", return_value=None),
        ):
            import contextlib

            from engine.cli import main

            # health should NOT be blocked even with no identity
            with contextlib.suppress(SystemExit):
                main(["health"])

            out = capsys.readouterr().out + capsys.readouterr().err

            # The gate must not have returned IDENTITY_REQUIRED
            assert "IDENTITY_REQUIRED" not in out
