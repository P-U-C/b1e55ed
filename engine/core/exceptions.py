"""engine.core.exceptions

Errors are part of the interface.

Dry, precise, structural. (No exclamation marks.)
"""

from __future__ import annotations


class B1e55edError(Exception):
    """Base exception for b1e55ed."""


class ConfigError(B1e55edError):
    """Configuration is missing, invalid, or inconsistent."""


class EventStoreError(B1e55edError):
    """Event store failures: schema, IO, integrity, or invariants."""


class ProducerError(B1e55edError):
    """Producer contract violations or collection failures."""


class KillSwitchError(B1e55edError):
    """Kill switch engaged or misconfigured."""


class PreflightError(B1e55edError):
    """Execution preflight checks failed."""


class SecurityError(B1e55edError):
    """Security invariant violated."""


class InsufficientBalanceError(PreflightError):
    """You are not a whale. Act accordingly."""


class LeverageExceededError(PreflightError):
    """Three Arrows tried this. Outcome documented."""


class StaleDataError(ProducerError):
    """This data is older than the last regime."""


class DedupeConflictError(EventStoreError):
    """Deduplication key reused with different payload."""
