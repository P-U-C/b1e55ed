"""Tier 1 — Component instantiation checks.

Verifies every registered producer, the orchestrator, OMS, and dashboard
can be constructed without errors. No network I/O.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Literal

from engine.doctor.tier0 import CheckResult

Status = Literal["pass", "warn", "fail"]


def check_producers() -> CheckResult:
    """Each registered producer instantiates without error."""
    try:
        from engine.core.client import DataClient
        from engine.core.database import Database
        from engine.core.metrics import REGISTRY
        from engine.producers.base import ProducerContext
        from engine.producers.registry import discover, get_producer, list_producers

        discover()
        names = list_producers()
        total = len(names)

        if total == 0:
            return CheckResult("producers", "warn", "No producers registered")

        # Use a temp DB so we don't touch production data
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_db = Database(Path(tmpdir) / "doctor.db")
            try:
                config = _load_config_safe()
                client = DataClient()
                logger = logging.getLogger("b1e55ed.doctor")
                pctx = ProducerContext(config=config, db=tmp_db, client=client, metrics=REGISTRY, logger=logger)

                errors: list[str] = []
                ok_count = 0
                for name in names:
                    try:
                        cls = get_producer(name)
                        _ = cls(pctx)  # type: ignore[call-arg]
                        ok_count += 1
                    except Exception as e:
                        errors.append(f"{name}: {type(e).__name__}: {e}")

                if not errors:
                    return CheckResult("producers", "pass", f"{ok_count}/{total} producers instantiate")
                else:
                    msg = f"{ok_count}/{total} producers OK; {len(errors)} failed"
                    detail = "; ".join(errors[:3])
                    if len(errors) > 3:
                        detail += f" (+{len(errors) - 3} more)"
                    return CheckResult("producers", "fail", f"{msg}: {detail}")
            finally:
                tmp_db.close()
    except Exception as e:
        return CheckResult("producers", "fail", f"Producer check failed: {e}")


def check_orchestrator() -> CheckResult:
    """BrainOrchestrator loads with temp DB."""
    try:
        import tempfile

        from engine.brain.orchestrator import BrainOrchestrator
        from engine.core.database import Database

        config = _load_config_safe()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_db = Database(Path(tmpdir) / "doctor.db")
            try:
                # Create a minimal identity for testing
                identity = _make_test_identity()
                BrainOrchestrator(config=config, db=tmp_db, identity=identity)
                return CheckResult("orchestrator", "pass", "BrainOrchestrator loads")
            finally:
                tmp_db.close()
    except Exception as e:
        return CheckResult("orchestrator", "fail", f"BrainOrchestrator failed: {type(e).__name__}: {e}")


def check_oms() -> CheckResult:
    """OMS initializes in paper mode."""
    try:
        import tempfile

        from engine.brain.kill_switch import KillSwitch
        from engine.core.database import Database
        from engine.core.policy import TradingPolicyEngine
        from engine.execution.oms import OMS
        from engine.execution.position_sizer import CorrelationAwareSizer, PositionSizer
        from engine.execution.preflight import Preflight

        config = _load_config_safe()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_db = Database(Path(tmpdir) / "doctor.db")
            try:
                policy = TradingPolicyEngine(config)
                kill_switch = KillSwitch(config, tmp_db)
                preflight = Preflight(policy=policy, kill_switch=kill_switch)
                base_sizer = PositionSizer()
                sizer = CorrelationAwareSizer(base=base_sizer)
                OMS(config=config, db=tmp_db, preflight=preflight, sizer=sizer)
                mode = getattr(config, "execution", None)
                mode_str = getattr(mode, "mode", "paper") if mode else "paper"
                return CheckResult("oms", "pass", f"OMS initializes (mode={mode_str})")
            finally:
                tmp_db.close()
    except Exception as e:
        return CheckResult("oms", "fail", f"OMS failed: {type(e).__name__}: {e}")


def check_oms_wired() -> CheckResult:
    """Check if OMS is wired into orchestrator on CLI brain path.

    Accept either:
    - constructor injection (`BrainOrchestrator(..., oms=...)`), or
    - post-init injection (`orchestrator._oms = ...`)
    """
    try:
        import inspect

        from engine.cli.main import _cmd_brain

        source = inspect.getsource(_cmd_brain)
        wired = ("oms=" in source) or ("_oms" in source and "orchestrator" in source)
        if wired:
            return CheckResult("oms_wired", "pass", "OMS wired into orchestrator")
        return CheckResult(
            "oms_wired",
            "warn",
            "OMS not wired into orchestrator (no constructor or post-init OMS injection found)",
            remediation="Inject OMS in cli/main.py _cmd_brain() before run_cycle",
        )
    except Exception as e:
        return CheckResult("oms_wired", "warn", f"Could not inspect cli/main.py: {e}")


def check_dashboard() -> CheckResult:
    """Dashboard app imports without error."""
    try:
        import importlib

        mod = importlib.import_module("dashboard.app")
        app = getattr(mod, "app", None)
        if app is not None:
            return CheckResult("dashboard", "pass", "Dashboard app imports")
        return CheckResult("dashboard", "warn", "Dashboard module loaded but no 'app' attribute")
    except Exception as e:
        return CheckResult("dashboard", "fail", f"Dashboard import failed: {type(e).__name__}: {e}")


def _load_config_safe() -> Any:
    """Load config with fallback to defaults."""
    from engine.core.config import Config

    user_yaml = Path.home() / ".b1e55ed" / "config" / "user.yaml"
    if user_yaml.exists():
        try:
            return Config.from_yaml(user_yaml)
        except Exception:
            pass
    # Try repo defaults
    try:
        return Config.from_repo_defaults()
    except Exception:
        return Config()


def _make_test_identity() -> Any:
    """Create a minimal NodeIdentity for doctor checks."""
    from engine.security.identity import NodeIdentity

    return NodeIdentity(
        node_id="b1e55ed-doctor",
        public_key="0" * 64,
        private_key="0" * 64,
        created_at="2024-01-01T00:00:00+00:00",
    )


def run_tier1() -> list[CheckResult]:
    """Run all Tier 1 component checks."""
    return [
        check_producers(),
        check_orchestrator(),
        check_oms(),
        check_oms_wired(),
        check_dashboard(),
    ]
