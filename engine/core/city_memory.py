"""
City memory client — writes task outcomes to alpha-co knowledge graph via SSH.
Called from b1e55ed heartbeat/orchestrator after task completions.
Non-blocking: runs in daemon thread, never raises to caller.
"""

import json
import os
import subprocess
import threading
import uuid

ALPHA_CO_IP = "192.168.1.20"
SSH_KEY = os.path.expanduser("~/.ssh/b1e55ed_city")
CITY_REPO = "/home/ubuntu/city"
DB_PATH = "/home/ubuntu/datasette-data/knowledge.db"


def _ssh_write(python_code: str) -> bool:
    """Run python3 on alpha-co to write to the knowledge DB. Returns True on success."""
    try:
        cmd = [
            "ssh",
            "-i",
            SSH_KEY,
            "-n",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ConnectTimeout=5",
            f"ubuntu@{ALPHA_CO_IP}",
            f"cd {CITY_REPO} && CITY_MEMORY_DB={DB_PATH} python3 -c {json.dumps(python_code)}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.returncode == 0
    except Exception:
        return False


def _write_async(python_code: str):
    """Fire-and-forget SSH write in daemon thread."""
    t = threading.Thread(target=_ssh_write, args=(python_code,), daemon=True)
    t.start()


def log_task(
    agent_id: str,
    task_type: str,
    label: str,
    outcome: str,
    confidence: float = None,
    duration_s: int = None,
    metadata: dict = None,
):
    """
    Log a completed task to the city knowledge graph.
    Called after any significant b1e55ed operation completes.
    Non-blocking — fire and forget.

    Args:
        agent_id: e.g. "b1e55ed", "worker-1", "clawteam-engineering"
        task_type: e.g. "research", "trade_signal", "heartbeat_check", "alert"
        label: short description of what was done
        outcome: "success", "failure", "partial", "blocked"
        confidence: optional float 0-1
        duration_s: optional duration in seconds
        metadata: optional extra context dict
    """
    task_id = f"task:{uuid.uuid4().hex[:8]}"
    data = {
        "task_type": task_type,
        "outcome": outcome,
        "agent_id": agent_id,
    }
    if confidence is not None:
        data["confidence"] = confidence
    if duration_s is not None:
        data["duration_s"] = duration_s
    if metadata:
        data.update(metadata)

    code = f"""
import sys
sys.path.insert(0, 'infra')
from memory import init_db, write_node, write_edge, log_event, DB_PATH
init_db()
task_id = write_node("task", {json.dumps(label)}, {json.dumps(data)}, node_id={json.dumps(task_id)})
write_edge({json.dumps(f"agent:{agent_id}")}, task_id, "completed")
log_event({json.dumps(agent_id)}, "task_complete", {json.dumps({"task_id": task_id, "outcome": outcome, "task_type": task_type})})
"""
    _write_async(code)


def log_signal(symbol: str, direction: str, confidence: float, source: str = "b1e55ed"):
    """Log a trade signal emission."""
    log_task(
        agent_id=source,
        task_type="trade_signal",
        label=f"Signal: {direction} {symbol}",
        outcome="emitted",
        confidence=confidence,
        metadata={"symbol": symbol, "direction": direction},
    )


def log_alert(alert_type: str, message: str, severity: str = "info"):
    """Log an alert (kill switch, position alert, etc.)."""
    log_task(
        agent_id="b1e55ed",
        task_type="alert",
        label=f"Alert: {alert_type}",
        outcome="triggered",
        metadata={"alert_type": alert_type, "message": message[:200], "severity": severity},
    )


def log_heartbeat(checks_run: list, issues: list = None):
    """Log a heartbeat cycle completion."""
    log_task(
        agent_id="b1e55ed",
        task_type="heartbeat",
        label=f"Heartbeat: {len(checks_run)} checks",
        outcome="success" if not issues else "partial",
        metadata={"checks": checks_run, "issues": issues or []},
    )
