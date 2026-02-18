"""engine.execution.preflight

Preflight checks gate execution.

Sprint 2B tests only require a minimal, deterministic implementation.
The full policy/kill-switch integration is built out in the full Phase 2 work.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    reason: str | None = None


class Preflight:
    def check(self, *, mode: str, symbol: str, size_notional: float) -> PreflightResult:
        if mode not in {"paper", "live"}:
            return PreflightResult(ok=False, reason="invalid_mode")
        if not symbol:
            return PreflightResult(ok=False, reason="missing_symbol")
        if size_notional <= 0:
            return PreflightResult(ok=False, reason="invalid_size")
        return PreflightResult(ok=True)
