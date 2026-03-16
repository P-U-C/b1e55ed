"""engine.cli.commands.daemon

Process supervisor for b1e55ed. Manages all subsystems as coordinated child processes.

Usage: b1e55ed daemon [--status]

Architecture:
  Service   — always-on process, restarts on exit (api, dashboard)
  Scheduler — periodic one-shot task (brain, resolver)
  Supervisor — coordinates all, handles signals, logs per-process
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from engine.core.paths import logs_dir

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_LOG_BACKUP_COUNT = 3


def _make_logger(name: str, log_path: Path) -> logging.Logger:
    """Create a per-process rotating file logger."""
    logger = logging.getLogger(f"daemon.{name}")
    logger.propagate = False
    if not logger.handlers:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_path, maxBytes=_LOG_MAX_BYTES, backupCount=_LOG_BACKUP_COUNT)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


# ---------------------------------------------------------------------------
# Service — always-on process (api, dashboard)
# ---------------------------------------------------------------------------

_HEALTHY_THRESHOLD = 10.0  # seconds running without crash → healthy


@dataclass
class Service:
    name: str
    cmd: list[str]
    restart_delay: float = 5.0
    log_path: Path | None = None

    # Runtime state (not constructor args)
    process: asyncio.subprocess.Process | None = field(default=None, repr=False)
    restarts: int = 0
    healthy: bool = False
    _started_at: float = 0.0
    _logger: logging.Logger | None = field(default=None, repr=False)

    def _init_logger(self) -> None:
        if self.log_path and self._logger is None:
            self._logger = _make_logger(self.name, self.log_path)


# ---------------------------------------------------------------------------
# Scheduler — periodic one-shot task (brain, resolver)
# ---------------------------------------------------------------------------


@dataclass
class Scheduler:
    name: str
    cmd: list[str]
    interval: int  # seconds between runs
    wait_for: str | None = None  # wait for this Service to be healthy first
    log_path: Path | None = None

    # Runtime state
    last_run: float = 0.0
    running: bool = False
    _logger: logging.Logger | None = field(default=None, repr=False)
    _active_proc: Any = field(default=None, repr=False)  # asyncio.subprocess.Process | None

    def _init_logger(self) -> None:
        if self.log_path and self._logger is None:
            self._logger = _make_logger(self.name, self.log_path)


# ---------------------------------------------------------------------------
# Supervisor — orchestrates everything
# ---------------------------------------------------------------------------


# Δαίμων (daimon): a spirit between gods and mortals, attending to tasks
# humans should not have to. Maxwell imagined one sorting molecules. We sort processes.
class Supervisor:
    def __init__(
        self,
        services: list[Service],
        schedulers: list[Scheduler],
        *,
        log_dir: Path,
        api_port: int = 5050,
    ) -> None:
        self.services = services
        self.schedulers = schedulers
        self.log_dir = log_dir
        self.api_port = api_port
        self._stopping = False
        self._service_map: dict[str, Service] = {s.name: s for s in services}

    # -- public entry -------------------------------------------------------

    async def run(self) -> None:
        """Main supervisor loop."""
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Assign log paths
        for svc in self.services:
            svc.log_path = self.log_dir / f"{svc.name}.log"
            svc._init_logger()
        for sch in self.schedulers:
            sch.log_path = self.log_dir / f"{sch.name}.log"
            sch._init_logger()

        # Register signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._request_shutdown)

        # Start all services
        for svc in self.services:
            asyncio.create_task(self._run_service(svc))

        # Start scheduler loops immediately — each scheduler's wait_for field
        # handles dependency ordering, so we don't block here.  This avoids a
        # race where a long API health-check timeout could delay schedulers
        # past a requested shutdown.
        scheduler_tasks = [asyncio.create_task(self._run_scheduler(sch)) for sch in self.schedulers]

        # Eagerly check API health so we can log readiness (non-blocking for schedulers).
        if self.services:
            asyncio.create_task(self._log_api_health())

        # Wait until shutdown requested
        try:
            while not self._stopping:
                await asyncio.sleep(1)
                # Update health status for services
                now = time.monotonic()
                for svc in self.services:
                    if svc.process and svc.process.returncode is None:
                        if now - svc._started_at > _HEALTHY_THRESHOLD:
                            svc.healthy = True
                    else:
                        svc.healthy = False
        except asyncio.CancelledError:
            pass

        # Graceful shutdown
        await self._shutdown()

        # Cancel scheduler tasks
        for t in scheduler_tasks:
            t.cancel()
        await asyncio.gather(*scheduler_tasks, return_exceptions=True)

    # -- service management -------------------------------------------------

    async def _run_service(self, svc: Service) -> None:
        """Run a service, restarting on exit until shutdown."""
        while not self._stopping:
            self._log_supervisor(f"Starting {svc.name}: {' '.join(svc.cmd)}")
            try:
                svc.process = await asyncio.create_subprocess_exec(
                    *svc.cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                svc._started_at = time.monotonic()
                svc.healthy = False

                # Stream output
                if svc.process.stdout:
                    await self._stream_output(svc.name, svc.process.stdout, svc._logger)

                returncode = await svc.process.wait()
                svc.healthy = False
                svc.process = None

                if self._stopping:
                    break

                svc.restarts += 1
                self._log_supervisor(f"{svc.name} exited (code={returncode}), restart #{svc.restarts} in {svc.restart_delay}s")
                await asyncio.sleep(svc.restart_delay)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log_supervisor(f"{svc.name} error: {exc}")
                if not self._stopping:
                    await asyncio.sleep(svc.restart_delay)

    # -- scheduler management -----------------------------------------------

    async def _run_scheduler(self, sch: Scheduler) -> None:
        """Periodically run a one-shot command."""
        while not self._stopping:
            try:
                # Wait until interval elapsed
                elapsed = time.monotonic() - sch.last_run
                remaining = sch.interval - elapsed
                if remaining > 0 and sch.last_run > 0:
                    await asyncio.sleep(min(remaining, 5.0))
                    continue

                # Check dependency
                if sch.wait_for:
                    dep = self._service_map.get(sch.wait_for)
                    if dep and not dep.healthy:
                        self._log_supervisor(f"{sch.name}: waiting for {sch.wait_for} to be healthy")
                        await asyncio.sleep(10)
                        continue

                # Run the task
                sch.running = True
                self._log_supervisor(f"Running {sch.name}: {' '.join(sch.cmd)}")
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *sch.cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    sch._active_proc = proc
                    try:
                        if proc.stdout:
                            await self._stream_output(sch.name, proc.stdout, sch._logger)
                        returncode = await proc.wait()
                        self._log_supervisor(f"{sch.name} finished (code={returncode})")
                    finally:
                        sch._active_proc = None
                except Exception as exc:
                    self._log_supervisor(f"{sch.name} error: {exc}")
                finally:
                    sch.running = False
                    sch.last_run = time.monotonic()

            except asyncio.CancelledError:
                break

    # -- output streaming ---------------------------------------------------

    async def _stream_output(
        self,
        name: str,
        stream: asyncio.StreamReader,
        logger: logging.Logger | None,
    ) -> None:
        """Read lines from subprocess stdout and log them."""
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            # Print to supervisor stdout (journald captures this)
            print(f"[{name}] {text}", flush=True)
            # Write to rotating log file
            if logger:
                logger.info(text)

    # -- health check -------------------------------------------------------

    async def _log_api_health(self, timeout: float = 30.0) -> None:
        """Background task: wait for API and log readiness (informational only)."""
        healthy = await self._wait_for_api_healthy(timeout=timeout)
        if healthy:
            self._log_supervisor("API healthy")
        else:
            self._log_supervisor("API did not become healthy within timeout")

    async def _wait_for_api_healthy(self, timeout: float = 30.0) -> bool:
        """Poll the API health endpoint until it responds OK."""
        import urllib.request

        url = f"http://127.0.0.1:{self.api_port}/api/v1/health"
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if self._stopping:
                return False
            try:
                resp = urllib.request.urlopen(url, timeout=2)  # noqa: S310
                data = json.loads(resp.read())
                if data.get("status") == "ok":
                    return True
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(2)
        return False

    # -- shutdown -----------------------------------------------------------

    def _request_shutdown(self) -> None:
        """Signal handler callback — sets shutdown flag."""
        if not self._stopping:
            self._log_supervisor("Shutdown requested")
            self._stopping = True

    # The mercy of SIGTERM, the certainty of SIGKILL.
    # Every daemon answers to something.
    async def _shutdown(self) -> None:
        """SIGTERM cascade to all children, wait up to 10s, then SIGKILL."""
        self._log_supervisor("Shutting down all processes...")

        # Send SIGTERM to all service processes
        for svc in self.services:
            if svc.process and svc.process.returncode is None:
                try:
                    svc.process.terminate()
                    self._log_supervisor(f"Sent SIGTERM to {svc.name} (pid={svc.process.pid})")
                except ProcessLookupError:
                    pass

        # Send SIGTERM to any active scheduler subprocess (brain, resolver, etc.)
        for sch in self.schedulers:
            if sch._active_proc and sch._active_proc.returncode is None:
                try:
                    sch._active_proc.terminate()
                    self._log_supervisor(f"Sent SIGTERM to {sch.name} scheduler (pid={sch._active_proc.pid})")
                except ProcessLookupError:
                    pass

        # Wait up to 10 seconds for all services to exit
        deadline = time.monotonic() + 10.0
        for svc in self.services:
            if svc.process and svc.process.returncode is None:
                remaining = max(0.1, deadline - time.monotonic())
                try:
                    await asyncio.wait_for(svc.process.wait(), timeout=remaining)
                    self._log_supervisor(f"{svc.name} exited cleanly")
                except TimeoutError:
                    # Force kill
                    try:
                        svc.process.kill()
                        self._log_supervisor(f"Sent SIGKILL to {svc.name}")
                    except ProcessLookupError:
                        pass

        # Wait up to 10 seconds for active scheduler processes to exit
        sched_deadline = time.monotonic() + 10.0
        for sch in self.schedulers:
            if sch._active_proc and sch._active_proc.returncode is None:
                remaining = max(0.1, sched_deadline - time.monotonic())
                try:
                    await asyncio.wait_for(sch._active_proc.wait(), timeout=remaining)
                    self._log_supervisor(f"{sch.name} scheduler exited cleanly")
                except TimeoutError:
                    try:
                        sch._active_proc.kill()
                        self._log_supervisor(f"Sent SIGKILL to {sch.name} scheduler")
                    except ProcessLookupError:
                        pass

        self._log_supervisor("All processes stopped")

    # -- logging helper -----------------------------------------------------

    def _log_supervisor(self, msg: str) -> None:
        print(f"[supervisor] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Status command
# ---------------------------------------------------------------------------


def _show_status() -> int:
    """Show daemon status by checking running processes."""
    import subprocess as sp

    print("b1e55ed daemon status")
    print("=" * 40)

    # Check for running b1e55ed processes
    try:
        result = sp.run(
            ["pgrep", "-af", "b1e55ed"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout.strip():
            print("\nRunning processes:")
            for line in result.stdout.strip().split("\n"):
                print(f"  {line}")
        else:
            print("\nNo b1e55ed processes found.")
    except FileNotFoundError:
        print("\n(pgrep not available)")

    # Check log directory
    log_dir = logs_dir()
    if log_dir.exists():
        print(f"\nLog directory: {log_dir}")
        for f in sorted(log_dir.glob("*.log")):
            size = f.stat().st_size
            print(f"  {f.name}: {size:,} bytes")
    else:
        print(f"\nLog directory not found: {log_dir}")

    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_daemon(repo_root: Path, config: Any) -> int:
    """Entry point from CLI. Returns exit code."""
    import shutil

    # Find the b1e55ed binary
    b1e55ed_bin = shutil.which("b1e55ed")
    if not b1e55ed_bin:
        b1e55ed_bin = sys.executable + " -m engine.cli"

    log_dir = logs_dir()

    # Read intervals from config (with safe defaults)
    daemon_cfg = getattr(config, "daemon", None)
    brain_interval = getattr(daemon_cfg, "brain_interval_seconds", 300)
    brain_full_interval = getattr(daemon_cfg, "brain_full_interval_seconds", 21600)
    resolver_interval = getattr(daemon_cfg, "resolver_interval_seconds", 1800)

    api_cfg = getattr(config, "api", None)
    api_port = getattr(api_cfg, "port", 5050)

    # Build command lists — handle both binary and "python -m" forms
    def _cmd(args: list[str]) -> list[str]:
        if b1e55ed_bin and " " not in b1e55ed_bin:
            return [b1e55ed_bin, *args]
        # Fallback: python -m engine.cli
        return [sys.executable, "-m", "engine.cli", *args]

    services = [
        Service("api", _cmd(["api", "--port", str(api_port)])),
        Service("dashboard", _cmd(["dashboard"])),
    ]
    schedulers = [
        Scheduler(
            "brain",
            _cmd(["brain"]),
            interval=brain_interval,
            wait_for="api",
        ),
        Scheduler(
            "brain-full",
            _cmd(["brain", "--full"]),
            interval=brain_full_interval,
            wait_for="api",
        ),
        Scheduler(
            "resolver",
            _cmd(["resolve-outcomes"]),
            interval=resolver_interval,
        ),
    ]

    supervisor = Supervisor(services, schedulers, log_dir=log_dir, api_port=api_port)

    print(f"b1e55ed daemon starting — logs: {log_dir}")
    print(f"  api:        always-on (port {api_port})")
    print("  dashboard:  always-on")
    print(f"  brain:      every {brain_interval}s ({brain_interval // 60}m)")
    print(f"  brain-full: every {brain_full_interval}s ({brain_full_interval // 3600}h)")
    print(f"  resolver:   every {resolver_interval}s ({resolver_interval // 60}m)")
    print()

    # Set PYTHONPATH so subprocesses can import engine
    if "PYTHONPATH" not in os.environ:
        os.environ["PYTHONPATH"] = str(repo_root)

    # Startup reconciliation: backfill provenance events lost in any prior crash.
    # Must run before schedulers start so the event bus is consistent from the first cycle.
    try:
        import logging as _logging

        from engine.core.database import Database as _Database
        from engine.core.paths import data_dir as _data_dir
        from engine.execution.oms import reconcile_execution_events

        _db_path = _data_dir() / "brain.db"
        if _db_path.exists():
            _db = _Database(_db_path)
            _result = reconcile_execution_events(_db)
            _db.close()
            _recon_logger = _logging.getLogger("b1e55ed.daemon")
            _recon_logger.info(f"Startup reconciliation: repaired {_result['signal_accepted']} missing attribution events")
            print(
                f"[daemon] Startup reconciliation: repaired {_result['signal_accepted']} missing attribution events",
                flush=True,
            )
    except Exception:
        pass

    import contextlib

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(supervisor.run())
    return 0
