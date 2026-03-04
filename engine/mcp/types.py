from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MCPSignalPayload:
    """Normalized signal payload emitted to the MCP server by any producer."""

    producer: str  # producer name e.g. "tradfi_basis"
    domain: str  # "technical" | "onchain" | "tradfi" | "social" | "events" | "curator" | "benchmark"
    asset: str | None  # e.g. "BTC", "ETH", None if domain-wide
    direction: str | None  # "long" | "short" | "flat" | None
    confidence: float | None  # 0.0–1.0, None if not applicable
    horizon: str | None  # e.g. "4h", "1d", None
    reason: str  # human-readable rationale
    timestamp: str  # ISO8601 UTC
    raw_score: float | None  # original 0–10 score if applicable, else None
    metadata: dict = field(default_factory=dict)  # producer-specific extras


@dataclass(frozen=True, slots=True)
class MCPProducerManifest:
    """Registry entry for a producer registered with the MCP server."""

    name: str  # producer name
    domain: str  # signal domain
    mcp_source_url: str | None  # URL of upstream MCP server (None = REST)
    description: str  # one-line description
    assets: list[str]  # assets this producer covers, empty = all
    schedule: str  # cron expression or "continuous"
    registered_at: str  # ISO8601 UTC


@dataclass
class MCPSignalBuffer:
    """Ring buffer of recent signals per producer. Not frozen — mutable by design."""

    producer: str
    capacity: int = 100
    signals: list = field(default_factory=list)  # list[MCPSignalPayload] for py310 compat

    def push(self, signal) -> None:
        """Append signal; evict oldest if over capacity."""
        self.signals.append(signal)
        if len(self.signals) > self.capacity:
            self.signals = self.signals[-self.capacity :]

    def latest(self):
        """Return most recent signal or None."""
        return self.signals[-1] if self.signals else None

    def recent(self, n: int = 10) -> list:
        """Return up to n most recent signals."""
        return self.signals[-n:]
