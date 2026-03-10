"""engine.mcp.server

b1e55ed MCP Server — exposes all producer signals as MCP tools/resources.

Dual-mode:
  - With mcp[cli] installed: full MCP protocol server (SSE transport, port 7337 default)
  - Without: registry-only mode (signals accessible via REST in S4)

Tools exposed:
  list_producers()                              → list of MCPProducerManifest dicts
  get_latest_signal(producer_name: str)         → MCPSignalPayload dict or None
  get_signal_history(producer_name: str, limit: int = 10) → list of MCPSignalPayload dicts

Start via: MCPServer(config).start_background() — runs in daemon thread, never blocks.
Stop via:  MCPServer(config).stop()
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from threading import Event, Lock, Thread
from typing import Any

from engine.mcp.registry import get_registry

logger = logging.getLogger(__name__)


class MCPServer:
    def __init__(self, port: int = 7337, enabled: bool = True):
        self.port = int(port)
        self.enabled = enabled

        self._registry = get_registry()
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._state_lock = Lock()
        self._running = False
        self._mcp_app: Any | None = None

    def start_background(self) -> None:
        """Start MCP server in a daemon thread. No-op if not enabled or already running."""

        if not self.enabled:
            return

        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return

        try:
            from mcp.server.fastmcp import FastMCP
        except ImportError:
            logger.warning("mcp_sdk_missing_registry_mode_only")
            return

        self._stop_event.clear()
        thread = Thread(target=self._serve, args=(FastMCP,), name="mcp-server", daemon=True)
        with self._state_lock:
            self._thread = thread
        thread.start()

    def stop(self) -> None:
        """Stop the server. No-op if not running."""

        with self._state_lock:
            thread = self._thread

        if thread is None:
            return

        self._stop_event.set()

        app = self._mcp_app
        if app is not None:
            for method_name in ("stop", "shutdown", "close"):
                method = getattr(app, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:  # noqa: BLE001
                        logger.debug("mcp_server_stop_method_failed", exc_info=True)
                    break

        if thread.is_alive():
            thread.join(timeout=1.0)

        with self._state_lock:
            if not thread.is_alive():
                self._thread = None
                self._running = False

    def is_running(self) -> bool:
        with self._state_lock:
            return bool(self._running and self._thread is not None and self._thread.is_alive())

    def tool_list_producers(self) -> list[dict]:
        return [asdict(manifest) for manifest in self._registry.list_producers()]

    def tool_get_latest_signal(self, producer_name: str) -> dict | None:
        latest = self._registry.get_latest(producer_name)
        if latest is None:
            return None
        return asdict(latest)

    def tool_get_signal_history(self, producer_name: str, limit: int = 10) -> list[dict]:
        try:
            n = int(limit)
        except (TypeError, ValueError):
            n = 10

        n = max(0, n)
        return [asdict(signal) for signal in self._registry.get_recent(producer_name, n=n)]

    def _serve(self, fastmcp_cls: Any) -> None:
        try:
            app = fastmcp_cls("b1e55ed-mcp")
            self._mcp_app = app

            @app.tool()  # type: ignore[untyped-decorator]
            def list_producers() -> list[dict]:
                return self.tool_list_producers()

            @app.tool()  # type: ignore[untyped-decorator]
            def get_latest_signal(producer_name: str) -> dict | None:
                return self.tool_get_latest_signal(producer_name)

            @app.tool()  # type: ignore[untyped-decorator]
            def get_signal_history(producer_name: str, limit: int = 10) -> list[dict]:
                return self.tool_get_signal_history(producer_name, limit)

            with self._state_lock:
                self._running = True

            # FastMCP API has changed across versions. Try common signatures.
            run_attempts: list[dict[str, Any]] = [
                {"transport": "sse", "host": "0.0.0.0", "port": self.port},
                {"transport": "sse", "port": self.port},
                {"port": self.port},
                {},
            ]

            for kwargs in run_attempts:
                try:
                    app.run(**kwargs)
                    return
                except TypeError:
                    continue

            logger.error("mcp_server_run_signature_unsupported")
        except Exception:  # noqa: BLE001
            logger.exception("mcp_server_failed")
        finally:
            with self._state_lock:
                self._running = False
