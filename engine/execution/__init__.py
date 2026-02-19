"""engine.execution

Execution layer: convert TradeIntents into Orders/Fills/Positions.

Sprint 2A ships the OMS + paper trading plumbing. Only two execution modes exist:
- ``paper``: simulated fills, persists to DB
- ``live``: adapter boundary (implemented in Sprint 2B)

No ``dry_run`` mode (DECISIONS_V3 #4).
"""

from __future__ import annotations

from engine.execution.circuit_breaker import CircuitBreaker, CircuitBreakerError, TokenBucket
from engine.execution.oms import OMS, OMSResult
from engine.execution.paper import PaperBroker, PaperFill
from engine.execution.pnl import PnLSnapshot, PnLTracker
from engine.execution.position_sizer import CorrelationAwareSizer, KellyParams, PositionSizer
from engine.execution.preflight import Preflight, PreflightError, PreflightResult

__all__ = [
    "OMS",
    "OMSResult",
    "PaperBroker",
    "PaperFill",
    "Preflight",
    "PreflightError",
    "PreflightResult",
    "PositionSizer",
    "KellyParams",
    "CorrelationAwareSizer",
    "PnLTracker",
    "PnLSnapshot",
    "TokenBucket",
    "CircuitBreaker",
    "CircuitBreakerError",
]
