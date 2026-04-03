import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from engine.core import city_memory


class TestCityMemory(unittest.TestCase):
    def test_log_task_constructs_correct_python_code_string(self):
        captured: dict[str, str] = {}

        with (
            patch(
                "engine.core.city_memory._write_async",
                side_effect=lambda code: captured.setdefault("code", code),
            ),
            patch("engine.core.city_memory.uuid.uuid4", return_value=SimpleNamespace(hex="abc12345def67890")),
        ):
            city_memory.log_task(
                agent_id="b1e55ed",
                task_type="research",
                label="Test task",
                outcome="success",
                confidence=0.9,
                duration_s=12,
                metadata={"symbol": "BTC"},
            )

        code = captured["code"]
        self.assertIn("sys.path.insert(0, 'infra')", code)
        self.assertIn('write_node("task", "Test task"', code)
        self.assertIn('node_id="task:abc12345"', code)
        self.assertIn('write_edge("agent:b1e55ed", task_id, "completed")', code)
        self.assertIn(
            'log_event("b1e55ed", "task_complete", {"task_id": "task:abc12345", "outcome": "success", "task_type": "research"})',
            code,
        )

    def test_log_signal_calls_log_task_with_trade_signal(self):
        with patch("engine.core.city_memory.log_task") as mock_log_task:
            city_memory.log_signal(symbol="BTC", direction="long", confidence=0.77, source="alpha-agent")

        mock_log_task.assert_called_once_with(
            agent_id="alpha-agent",
            task_type="trade_signal",
            label="Signal: long BTC",
            outcome="emitted",
            confidence=0.77,
            metadata={"symbol": "BTC", "direction": "long"},
        )

    def test_log_alert_calls_log_task_with_alert_type(self):
        with patch("engine.core.city_memory.log_task") as mock_log_task:
            city_memory.log_alert(alert_type="kill_switch", message="paused", severity="high")

        mock_log_task.assert_called_once_with(
            agent_id="b1e55ed",
            task_type="alert",
            label="Alert: kill_switch",
            outcome="triggered",
            metadata={"alert_type": "kill_switch", "message": "paused", "severity": "high"},
        )

    def test_log_heartbeat_no_issues_is_success(self):
        with patch("engine.core.city_memory.log_task") as mock_log_task:
            city_memory.log_heartbeat(checks_run=["price_check", "position_monitor"])

        mock_log_task.assert_called_once_with(
            agent_id="b1e55ed",
            task_type="heartbeat",
            label="Heartbeat: 2 checks",
            outcome="success",
            metadata={"checks": ["price_check", "position_monitor"], "issues": []},
        )

    def test_log_heartbeat_with_issues_is_partial(self):
        with patch("engine.core.city_memory.log_task") as mock_log_task:
            city_memory.log_heartbeat(checks_run=["price_check"], issues=["price feed stale"])

        mock_log_task.assert_called_once_with(
            agent_id="b1e55ed",
            task_type="heartbeat",
            label="Heartbeat: 1 checks",
            outcome="partial",
            metadata={"checks": ["price_check"], "issues": ["price feed stale"]},
        )

    def test_write_async_spawns_daemon_thread(self):
        fake_thread = MagicMock()
        with patch("engine.core.city_memory.threading.Thread", return_value=fake_thread) as mock_thread:
            city_memory._write_async("print('ok')")

        mock_thread.assert_called_once_with(target=city_memory._ssh_write, args=("print('ok')",), daemon=True)
        fake_thread.start.assert_called_once()

    def test_ssh_failure_is_caught_silently(self):
        with patch("engine.core.city_memory.subprocess.run", side_effect=RuntimeError("ssh down")):
            result = city_memory._ssh_write("print('ok')")

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
