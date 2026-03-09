"""Tier 0 — Preflight checks.

No heavy imports, no I/O beyond filesystem reads.
Validates the environment is sane before anything runs.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Status = Literal["pass", "warn", "fail"]


@dataclass
class CheckResult:
    name: str
    status: Status
    message: str
    remediation: str | None = None


def check_python_version(min_major: int = 3, min_minor: int = 11) -> CheckResult:
    """Python version >= 3.11 (per pyproject.toml requires-python)."""
    v = sys.version_info
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= (min_major, min_minor):
        return CheckResult("python_version", "pass", f"Python {version_str}")
    return CheckResult(
        "python_version",
        "warn",
        f"Python {version_str} (requires >= {min_major}.{min_minor})",
        remediation=f"Upgrade to Python >= {min_major}.{min_minor}",
    )


# Core packages that must be importable for any b1e55ed operation.
REQUIRED_PACKAGES = [
    "yaml",
    "pydantic",
    "pydantic_settings",
    "sqlite3",
    "httpx",
    "uvicorn",
    "fastapi",
    "jinja2",
]


def check_dependencies() -> CheckResult:
    """All required packages importable."""
    missing: list[str] = []
    for pkg in REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
    if not missing:
        return CheckResult("dependencies", "pass", "Dependencies installed")
    return CheckResult(
        "dependencies",
        "fail",
        f"Missing packages: {', '.join(missing)}",
        remediation="Run: uv sync  (or pip install -e .)",
    )


def check_user_config() -> CheckResult:
    """~/.b1e55ed/config/user.yaml exists and is valid YAML."""
    user_yaml = Path.home() / ".b1e55ed" / "config" / "user.yaml"
    if not user_yaml.exists():
        return CheckResult(
            "user_config",
            "warn",
            f"{user_yaml} not found",
            remediation="Run: b1e55ed setup",
        )
    try:
        import yaml

        yaml.safe_load(user_yaml.read_text())  # validate YAML syntax
        # Sanity: warn if config references /tmp paths (common test pollution)
        text = user_yaml.read_text()
        if "/tmp/" in text or "/tmp\\" in text:
            return CheckResult(
                "user_config",
                "warn",
                f"{user_yaml} contains /tmp paths (possible test pollution)",
                remediation=f"Edit {user_yaml} and remove /tmp references",
            )
        return CheckResult("user_config", "pass", f"{user_yaml} valid")
    except Exception as e:
        return CheckResult(
            "user_config",
            "fail",
            f"{user_yaml} parse error: {e}",
            remediation=f"Fix YAML syntax in {user_yaml}",
        )


def check_db_writable() -> CheckResult:
    """DB directory exists and is writable."""
    try:
        from engine.core.paths import data_dir

        dd = data_dir()
        dd.mkdir(parents=True, exist_ok=True)
        db_path = dd / "brain.db"
        # Check parent dir is writable
        import os

        if not os.access(str(dd), os.W_OK):
            return CheckResult(
                "db_writable",
                "fail",
                f"{dd} is not writable",
                remediation=f"Fix permissions: chmod u+w {dd}",
            )
        return CheckResult("db_writable", "pass", f"Database writable ({db_path})")
    except Exception as e:
        return CheckResult(
            "db_writable",
            "fail",
            f"Cannot verify DB path: {e}",
            remediation="Run: b1e55ed setup",
        )


def check_identity() -> CheckResult:
    """Identity file exists."""
    identity_dir = Path.home() / ".b1e55ed"
    # Check for identity.key (primary) or identity.json (forged identity)
    key_path = identity_dir / "identity.key"
    json_path = identity_dir / "identity.json"

    if key_path.exists():
        try:
            import json as _json

            data = _json.loads(key_path.read_text())
            node_id = data.get("node_id", "unknown")
            return CheckResult("identity", "pass", f"Identity: {node_id}")
        except Exception:
            return CheckResult("identity", "pass", f"Identity file exists: {key_path}")
    elif json_path.exists():
        try:
            import json

            data = json.loads(json_path.read_text())
            node_id = data.get("node_id", "unknown")
            return CheckResult("identity", "pass", f"Identity: {node_id}")
        except Exception:
            return CheckResult("identity", "pass", f"Identity file exists: {json_path}")
    else:
        return CheckResult(
            "identity",
            "warn",
            "No identity found",
            remediation="Run: b1e55ed identity forge",
        )


def check_kill_switch() -> CheckResult:
    """Kill switch level (warn if > 0)."""
    try:
        from engine.core.database import Database
        from engine.core.events import EventType
        from engine.core.paths import data_dir

        db_path = data_dir() / "brain.db"
        if not db_path.exists():
            return CheckResult("kill_switch", "pass", "Kill switch: SAFE (no DB yet)")

        db = Database(db_path)
        try:
            evs = db.get_events(event_type=EventType.KILL_SWITCH_V1, limit=1)
            if not evs:
                return CheckResult("kill_switch", "pass", "Kill switch: SAFE (level 0)")
            level = int(evs[0].payload.get("level", 0))
            if level == 0:
                return CheckResult("kill_switch", "pass", "Kill switch: SAFE (level 0)")

            level_name = {0: "SAFE", 1: "CAUTION", 2: "REDUCED", 3: "LOCKDOWN", 4: "HALT"}.get(level, f"L{level}")
            return CheckResult(
                "kill_switch",
                "warn",
                f"Kill switch: {level_name} (level {level})",
                remediation="Run: b1e55ed kill-switch set 0",
            )
        finally:
            db.close()
    except Exception as e:
        return CheckResult("kill_switch", "pass", f"Kill switch check skipped: {e}")


def run_tier0() -> list[CheckResult]:
    """Run all Tier 0 preflight checks."""
    return [
        check_python_version(),
        check_dependencies(),
        check_user_config(),
        check_db_writable(),
        check_identity(),
        check_kill_switch(),
    ]
