"""Tests for the unified daemon supervisor (engine.cli.commands.daemon).

Covers:
- Service / Scheduler / Supervisor dataclass construction
- Supervisor startup/shutdown lifecycle
- Scheduler dependency waits (wait_for)
- Health check polling
- Status command
- CLI wiring
- DaemonConfig in config.py
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.cli.commands.daemon import (
    Scheduler,
    Service,
    Supervisor,
    _show_status,
    run_daemon,
)

# ---------------------------------------------------------------------------
# Unit: Service dataclass
# ---------------------------------------------------------------------------


class TestService:
    def test_defaults(self) -> None:
        svc = Service(name="api", cmd=["echo", "hi"])
        assert svc.name == "api"
        assert svc.cmd == ["echo", "hi"]
        assert svc.restart_delay == 5.0
        assert svc.process is None
        assert svc.restarts == 0
        assert svc.healthy is False

    def test_init_logger_noop_without_log_path(self) -> None:
        svc = Service(name="api", cmd=["echo"])
        svc._init_logger()
        assert svc._logger is None

    def test_init_logger_creates_logger(self, tmp_path: Path) -> None:
        log_file = tmp_path / "api.log"
        svc = Service(name="api", cmd=["echo"], log_path=log_file)
        svc._init_logger()
        assert svc._logger is not None
        assert svc._logger.name == "daemon.api"

    def test_init_logger_idempotent(self, tmp_path: Path) -> None:
        log_file = tmp_path / "api.log"
        svc = Service(name="api", cmd=["echo"], log_path=log_file)
        svc._init_logger()
        logger1 = svc._logger
        svc._init_logger()
        assert svc._logger is logger1  # same instance


# ---------------------------------------------------------------------------
# Unit: Scheduler dataclass
# ---------------------------------------------------------------------------


class TestScheduler:
    def test_defaults(self) -> None:
        sch = Scheduler(name="brain", cmd=["b1e55ed", "brain"], interval=300)
        assert sch.name == "brain"
        assert sch.interval == 300
        assert sch.wait_for is None
        assert sch.last_run == 0.0
        assert sch.running is False

    def test_wait_for(self) -> None:
        sch = Scheduler(name="brain", cmd=["b1e55ed", "brain"], interval=300, wait_for="api")
        assert sch.wait_for == "api"

    def test_init_logger(self, tmp_path: Path) -> None:
        log_file = tmp_path / "brain.log"
        sch = Scheduler(name="brain", cmd=["echo"], interval=60, log_path=log_file)
        sch._init_logger()
        assert sch._logger is not None


# ---------------------------------------------------------------------------
# Unit: Supervisor construction
# ---------------------------------------------------------------------------


class TestSupervisorConstruction:
    def test_basic_construction(self, tmp_path: Path) -> None:
        services = [Service(name="api", cmd=["echo"])]
        schedulers = [Scheduler(name="brain", cmd=["echo"], interval=60)]
        sup = Supervisor(services, schedulers, log_dir=tmp_path / "logs")
        assert len(sup.services) == 1
        assert len(sup.schedulers) == 1
        assert sup.api_port == 5050

    def test_custom_api_port(self, tmp_path: Path) -> None:
        sup = Supervisor([], [], log_dir=tmp_path / "logs", api_port=8080)
        assert sup.api_port == 8080

    def test_service_map_built(self, tmp_path: Path) -> None:
        svc = Service(name="api", cmd=["echo"])
        sup = Supervisor([svc], [], log_dir=tmp_path / "logs")
        assert "api" in sup._service_map
        assert sup._service_map["api"] is svc


# ---------------------------------------------------------------------------
# Unit: Supervisor shutdown signal
# ---------------------------------------------------------------------------


class TestSupervisorShutdown:
    def test_request_shutdown_sets_flag(self, tmp_path: Path) -> None:
        sup = Supervisor([], [], log_dir=tmp_path / "logs")
        assert sup._stopping is False
        sup._request_shutdown()
        assert sup._stopping is True

    def test_request_shutdown_idempotent(self, tmp_path: Path) -> None:
        sup = Supervisor([], [], log_dir=tmp_path / "logs")
        sup._request_shutdown()
        sup._request_shutdown()  # should not raise
        assert sup._stopping is True


# ---------------------------------------------------------------------------
# Integration: Supervisor run with fast-exit services
# ---------------------------------------------------------------------------


class TestSupervisorRun:
    @pytest.mark.asyncio
    async def test_run_with_no_services(self, tmp_path: Path) -> None:
        """Supervisor with empty services/schedulers should start and stop cleanly."""
        sup = Supervisor([], [], log_dir=tmp_path / "logs")

        async def stop_soon() -> None:
            await asyncio.sleep(0.3)
            sup._request_shutdown()

        task = asyncio.create_task(stop_soon())
        await sup.run()
        await task
        assert sup._stopping is True

    @pytest.mark.asyncio
    async def test_run_creates_log_dir(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "daemon_logs"
        assert not log_dir.exists()
        sup = Supervisor([], [], log_dir=log_dir)

        async def stop_soon() -> None:
            await asyncio.sleep(0.2)
            sup._request_shutdown()

        task = asyncio.create_task(stop_soon())
        await sup.run()
        await task
        assert log_dir.exists()

    @pytest.mark.asyncio
    async def test_service_starts_and_exits(self, tmp_path: Path) -> None:
        """A service that exits immediately should trigger restart counting."""
        svc = Service(name="test_svc", cmd=[sys.executable, "-c", "pass"], restart_delay=0.1)
        sup = Supervisor([svc], [], log_dir=tmp_path / "logs")

        async def stop_after_restarts() -> None:
            # Wait for at least 1 restart
            for _ in range(20):
                await asyncio.sleep(0.2)
                if svc.restarts >= 1:
                    break
            sup._request_shutdown()

        task = asyncio.create_task(stop_after_restarts())
        await sup.run()
        await task
        assert svc.restarts >= 1

    @pytest.mark.asyncio
    async def test_service_becomes_healthy(self, tmp_path: Path) -> None:
        """A service that stays alive long enough should be marked healthy."""
        # Use a script that keeps stdout open (critical: _stream_output waits for EOF)
        script = "import sys, time\nwhile True:\n    sys.stdout.write('alive\\n')\n    sys.stdout.flush()\n    time.sleep(1)\n"
        svc = Service(
            name="long_svc",
            cmd=[sys.executable, "-c", script],
            restart_delay=0.1,
        )
        sup = Supervisor([svc], [], log_dir=tmp_path / "logs")

        # Patch _HEALTHY_THRESHOLD to speed up test
        import engine.cli.commands.daemon as daemon_mod

        original_threshold = daemon_mod._HEALTHY_THRESHOLD

        try:
            daemon_mod._HEALTHY_THRESHOLD = 0.5  # 0.5s instead of 10s — generous for CI

            # Patch _wait_for_api_healthy to return immediately so the monitor
            # loop (which updates svc.healthy) starts without delay.
            async def _fast_health(timeout: float = 1.0) -> bool:
                return False  # no API running — that's fine for this test

            sup._wait_for_api_healthy = _fast_health  # type: ignore[assignment]

            became_healthy = False

            async def check_and_stop() -> None:
                nonlocal became_healthy
                for _ in range(40):
                    await asyncio.sleep(0.3)
                    if svc.healthy:
                        became_healthy = True
                        break
                sup._request_shutdown()

            task = asyncio.create_task(check_and_stop())
            await sup.run()
            await task
            # Check the flag captured before shutdown (shutdown resets svc.healthy to False)
            assert became_healthy
        finally:
            daemon_mod._HEALTHY_THRESHOLD = original_threshold

    @pytest.mark.asyncio
    async def test_scheduler_runs_task(self, tmp_path: Path) -> None:
        """Scheduler should execute its command after the interval."""
        marker = tmp_path / "scheduler_ran.txt"
        sch = Scheduler(
            name="test_sch",
            cmd=[sys.executable, "-c", f"from pathlib import Path; Path('{marker}').write_text('done')"],
            interval=1,
        )
        sup = Supervisor([], [sch], log_dir=tmp_path / "logs")

        # Patch health check to return instantly
        async def _fast_health(timeout: float = 1.0) -> bool:
            return True

        sup._wait_for_api_healthy = _fast_health  # type: ignore[assignment]

        async def stop_after_run() -> None:
            for _ in range(30):
                await asyncio.sleep(0.5)
                if marker.exists():
                    break
            sup._request_shutdown()

        task = asyncio.create_task(stop_after_run())
        await sup.run()
        await task
        assert marker.exists()
        assert marker.read_text() == "done"

    @pytest.mark.asyncio
    async def test_scheduler_waits_for_dependency(self, tmp_path: Path) -> None:
        """Scheduler with wait_for should not run until the dependency is healthy."""
        marker = tmp_path / "dep_ran.txt"
        svc = Service(name="api", cmd=[sys.executable, "-c", "import sys,time\nwhile True:\n sys.stdout.write('x\\n')\n sys.stdout.flush()\n time.sleep(1)\n"])
        sch = Scheduler(
            name="brain",
            cmd=[sys.executable, "-c", f"from pathlib import Path; Path('{marker}').write_text('ok')"],
            interval=1,
            wait_for="api",
        )
        sup = Supervisor([svc], [sch], log_dir=tmp_path / "logs")

        # Patch health check to return instantly
        async def _fast_health(timeout: float = 1.0) -> bool:
            return False

        sup._wait_for_api_healthy = _fast_health  # type: ignore[assignment]

        async def stop_soon() -> None:
            # Stop quickly — the scheduler should not have run because api isn't healthy yet
            await asyncio.sleep(2)
            sup._request_shutdown()

        task = asyncio.create_task(stop_soon())
        await sup.run()
        await task
        # The api service hasn't been running long enough to be healthy (10s threshold),
        # so the scheduler should NOT have run
        assert not marker.exists()

    @pytest.mark.asyncio
    async def test_shutdown_terminates_services(self, tmp_path: Path) -> None:
        """Graceful shutdown should terminate running service processes."""
        script = "import sys,time\nwhile True:\n sys.stdout.write('x\\n')\n sys.stdout.flush()\n time.sleep(1)\n"
        svc = Service(name="sleeper", cmd=[sys.executable, "-c", script])
        sup = Supervisor([svc], [], log_dir=tmp_path / "logs")

        # Patch health check to return instantly
        async def _fast_health(timeout: float = 1.0) -> bool:
            return False

        sup._wait_for_api_healthy = _fast_health  # type: ignore[assignment]

        async def stop_after_start() -> None:
            for _ in range(20):
                await asyncio.sleep(0.2)
                if svc.process is not None:
                    break
            sup._request_shutdown()

        task = asyncio.create_task(stop_after_start())
        await sup.run()
        await task
        # After shutdown, process should be terminated
        assert svc.process is None or svc.process.returncode is not None

    @pytest.mark.asyncio
    async def test_log_files_created(self, tmp_path: Path) -> None:
        """Log paths should be assigned to services and schedulers."""
        svc = Service(name="api", cmd=[sys.executable, "-c", "print('hello')"])
        sch = Scheduler(name="brain", cmd=[sys.executable, "-c", "pass"], interval=9999)
        log_dir = tmp_path / "logs"
        sup = Supervisor([svc], [sch], log_dir=log_dir)

        async def _fast_health(timeout: float = 1.0) -> bool:
            return False

        sup._wait_for_api_healthy = _fast_health  # type: ignore[assignment]

        async def stop_soon() -> None:
            await asyncio.sleep(0.5)
            sup._request_shutdown()

        task = asyncio.create_task(stop_soon())
        await sup.run()
        await task
        assert svc.log_path == log_dir / "api.log"
        assert sch.log_path == log_dir / "brain.log"


# ---------------------------------------------------------------------------
# Unit: Health check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_timeout(self, tmp_path: Path) -> None:
        """Health check should return False when API isn't running."""
        sup = Supervisor([], [], log_dir=tmp_path / "logs", api_port=59999)
        result = await sup._wait_for_api_healthy(timeout=1.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_stops_on_shutdown(self, tmp_path: Path) -> None:
        """Health check should return False when shutdown is requested."""
        sup = Supervisor([], [], log_dir=tmp_path / "logs", api_port=59999)
        sup._stopping = True
        result = await sup._wait_for_api_healthy(timeout=5.0)
        assert result is False


# ---------------------------------------------------------------------------
# Unit: Status command
# ---------------------------------------------------------------------------


class TestShowStatus:
    def test_show_status_returns_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _show_status()
        assert rc == 0
        out = capsys.readouterr().out
        assert "b1e55ed daemon status" in out


# ---------------------------------------------------------------------------
# Config: DaemonConfig
# ---------------------------------------------------------------------------


class TestDaemonConfig:
    def test_daemon_config_defaults(self) -> None:
        from engine.core.config import DaemonConfig

        cfg = DaemonConfig()
        assert cfg.brain_interval_seconds == 300
        assert cfg.brain_full_interval_seconds == 21600
        assert cfg.resolver_interval_seconds == 1800

    def test_daemon_config_custom(self) -> None:
        from engine.core.config import DaemonConfig

        cfg = DaemonConfig(
            brain_interval_seconds=60,
            brain_full_interval_seconds=3600,
            resolver_interval_seconds=600,
        )
        assert cfg.brain_interval_seconds == 60
        assert cfg.brain_full_interval_seconds == 3600
        assert cfg.resolver_interval_seconds == 600

    def test_config_has_daemon_field(self) -> None:
        from engine.core.config import Config

        cfg = Config()
        assert hasattr(cfg, "daemon")
        assert cfg.daemon.brain_interval_seconds == 300

    def test_daemon_config_from_yaml(self, tmp_path: Path) -> None:
        """DaemonConfig should be loadable from YAML."""
        from engine.core.config import Config

        repo_root = Path(__file__).resolve().parents[2]
        cfg_dir = tmp_path / "config"
        presets_dir = cfg_dir / "presets"
        presets_dir.mkdir(parents=True)

        shutil.copy2(repo_root / "config" / "default.yaml", cfg_dir / "default.yaml")
        shutil.copytree(repo_root / "config" / "presets", presets_dir, dirs_exist_ok=True)

        # Write a user.yaml with custom daemon config
        user_yaml = cfg_dir / "user.yaml"
        user_yaml.write_text(
            "preset: balanced\ndaemon:\n  brain_interval_seconds: 120\n  brain_full_interval_seconds: 7200\n  resolver_interval_seconds: 900\n"
        )

        cfg = Config.from_yaml(user_yaml)
        assert cfg.daemon.brain_interval_seconds == 120
        assert cfg.daemon.brain_full_interval_seconds == 7200
        assert cfg.daemon.resolver_interval_seconds == 900

    def test_default_yaml_has_daemon_section(self) -> None:
        """Verify config/default.yaml includes daemon settings."""
        import yaml

        repo_root = Path(__file__).resolve().parents[2]
        default_yaml = repo_root / "config" / "default.yaml"
        data = yaml.safe_load(default_yaml.read_text())
        assert "daemon" in data
        assert data["daemon"]["brain_interval_seconds"] == 300
        assert data["daemon"]["brain_full_interval_seconds"] == 21600
        assert data["daemon"]["resolver_interval_seconds"] == 1800


# ---------------------------------------------------------------------------
# CLI: daemon subcommand wiring
# ---------------------------------------------------------------------------


class TestCLIDaemon:
    def test_daemon_parser_exists(self) -> None:
        from engine.cli.main import build_parser

        parser = build_parser()
        # Verify 'daemon' is a valid subcommand by parsing --status
        args = parser.parse_args(["daemon", "--status"])
        assert args.command == "daemon"
        assert args.status is True

    def test_daemon_parser_no_args(self) -> None:
        from engine.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["daemon"])
        assert args.command == "daemon"
        assert args.status is False

    def test_daemon_status_via_main(self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
        """b1e55ed daemon --status should work via CLI main."""
        from engine.cli.main import main

        repo_root = Path(__file__).resolve().parents[2]
        monkeypatch.chdir(repo_root)

        # daemon --status doesn't need identity gate
        monkeypatch.setenv("B1E55ED_DEV_MODE", "1")
        rc = main(["daemon", "--status"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "b1e55ed daemon status" in out


# ---------------------------------------------------------------------------
# Integration: run_daemon entry point
# ---------------------------------------------------------------------------


class TestRunDaemon:
    def test_run_daemon_with_mock_config(self, tmp_path: Path) -> None:
        """run_daemon should accept a config and set up the supervisor."""

        config = MagicMock()
        config.daemon.brain_interval_seconds = 60
        config.daemon.brain_full_interval_seconds = 3600
        config.daemon.resolver_interval_seconds = 600
        config.api.port = 5050

        # Patch asyncio.run to avoid actually running the supervisor
        with patch("asyncio.run") as mock_run:
            rc = run_daemon(tmp_path, config)
            assert rc == 0
            # asyncio.run should have been called with the supervisor
            assert mock_run.called
