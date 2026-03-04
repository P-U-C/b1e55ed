from __future__ import annotations

from datetime import datetime, timedelta

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from pathlib import Path

from engine.core.database import Database
from engine.security.audit import AuditLogger


def test_audit_log_writes_and_queries(temp_dir: Path) -> None:
    db = Database(temp_dir / "test.db")
    audit = AuditLogger(db, component="unit")

    audit.log_action("KEY_ACCESS", actor="tester", details={"name": "X"})
    audit.log_action("CONFIG_CHANGE", actor="tester", details={"k": "v"})

    rows = audit.query(action_type="KEY_ACCESS")
    assert len(rows) == 1
    assert rows[0]["actor"] == "tester"
    assert rows[0]["details"]["name"] == "X"

    since = datetime.now(tz=UTC) - timedelta(days=1)
    rows2 = audit.query(since=since)
    assert len(rows2) >= 2

    db.close()
