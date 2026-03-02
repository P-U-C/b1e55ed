"""engine.mcp.registry

MCPProducerRegistry — shared in-memory state for the MCP layer.

Thread-safe singleton. Producers self-register on __init__ and push signals
on every publish(). The MCP server and REST endpoints read from here.

Designed as a module-level singleton (get_registry()) so it survives across
multiple producer instances without being passed through ProducerContext.
"""

from __future__ import annotations

from threading import Lock
from typing import cast

from engine.mcp.types import MCPProducerManifest, MCPSignalBuffer, MCPSignalPayload

_REGISTRY: MCPProducerRegistry | None = None
_REGISTRY_LOCK = Lock()


class MCPProducerRegistry:
    """Thread-safe registry of all producers and their recent signals."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._manifests: dict[str, MCPProducerManifest] = {}
        self._buffers: dict[str, MCPSignalBuffer] = {}

    def register(self, manifest: MCPProducerManifest) -> None:
        """Register a producer. Idempotent — re-registration updates the manifest."""

        with self._lock:
            self._manifests[manifest.name] = manifest
            self._buffers.setdefault(manifest.name, MCPSignalBuffer(producer=manifest.name))

    def push_signal(self, signal: MCPSignalPayload) -> None:
        """Append a signal to the producer's ring buffer. Creates buffer if first push."""

        with self._lock:
            if signal.producer not in self._buffers:
                self._buffers[signal.producer] = MCPSignalBuffer(producer=signal.producer)
            self._buffers[signal.producer].push(signal)

    def get_latest(self, producer: str) -> MCPSignalPayload | None:
        """Return most recent signal for a producer, or None."""

        with self._lock:
            buffer = self._buffers.get(producer)
            if buffer is None or not buffer.signals:
                return None
            return cast(MCPSignalPayload, buffer.signals[-1])

    def get_recent(self, producer: str, n: int = 10) -> list[MCPSignalPayload]:
        """Return up to n recent signals for a producer."""

        if n <= 0:
            return []

        with self._lock:
            buffer = self._buffers.get(producer)
            if buffer is None:
                return []

            if n >= len(buffer.signals):
                window = list(buffer.signals)
            else:
                window = buffer.signals[-n:]
            return [cast(MCPSignalPayload, signal) for signal in window]

    def list_producers(self) -> list[MCPProducerManifest]:
        """Return all registered producer manifests, sorted by name."""

        with self._lock:
            return [self._manifests[name] for name in sorted(self._manifests.keys())]

    def stats(self) -> dict:
        """Return registry stats: producer count, total signals buffered."""

        with self._lock:
            return {
                "producer_count": len(self._manifests),
                "total_signals_buffered": sum(len(buffer.signals) for buffer in self._buffers.values()),
            }


def get_registry() -> MCPProducerRegistry:
    """Return the module-level singleton registry."""

    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = MCPProducerRegistry()
        return _REGISTRY
