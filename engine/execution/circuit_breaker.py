"""engine.execution.circuit_breaker

Sprint 2A requires:
- token bucket rate limiting
- exponential backoff after failures

This module is intentionally small and dependency-free.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")


class CircuitBreakerError(RuntimeError):
    pass


@dataclass(slots=True)
class TokenBucket:
    """A simple token bucket.

    Tokens refill continuously at ``refill_rate_per_s`` up to ``capacity``.
    """

    capacity: float
    refill_rate_per_s: float
    tokens: float | None = None
    updated_at: float | None = None

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError("capacity must be > 0")
        if self.refill_rate_per_s <= 0:
            raise ValueError("refill_rate_per_s must be > 0")
        if self.tokens is None:
            self.tokens = float(self.capacity)
        if self.updated_at is None:
            self.updated_at = time.monotonic()

    def _refill(self, now: float) -> None:
        assert self.tokens is not None
        assert self.updated_at is not None
        dt = max(0.0, now - self.updated_at)
        self.tokens = min(self.capacity, self.tokens + dt * self.refill_rate_per_s)
        self.updated_at = now

    def try_take(self, amount: float = 1.0, *, now: float | None = None) -> bool:
        if amount <= 0:
            return True
        n = time.monotonic() if now is None else float(now)
        self._refill(n)
        assert self.tokens is not None
        if self.tokens + 1e-12 < amount:
            return False
        self.tokens -= amount
        return True

    def wait_time_s(self, amount: float = 1.0, *, now: float | None = None) -> float:
        """Return how many seconds until ``amount`` tokens are available."""

        if amount <= 0:
            return 0.0
        n = time.monotonic() if now is None else float(now)
        self._refill(n)
        assert self.tokens is not None
        if self.tokens >= amount:
            return 0.0
        missing = amount - self.tokens
        return float(missing / self.refill_rate_per_s)


@dataclass(slots=True)
class CircuitBreaker:
    """Token-bucket limiter + exponential backoff.

    Conceptually:
    - token bucket limits steady-state request rate
    - failures push the circuit into a backoff window

    This is *per venue* (or per external dependency).
    """

    name: str
    bucket: TokenBucket
    failure_threshold: int = 3
    backoff_base_s: float = 1.0
    backoff_max_s: float = 60.0

    failures: int = 0
    blocked_until: float = 0.0

    def _now(self) -> float:
        return time.monotonic()

    def can_call(self, *, now: float | None = None) -> bool:
        n = self._now() if now is None else float(now)
        if n < self.blocked_until:
            return False
        return self.bucket.try_take(1.0, now=n)

    def backoff_remaining_s(self, *, now: float | None = None) -> float:
        n = self._now() if now is None else float(now)
        return max(0.0, self.blocked_until - n)

    def record_success(self) -> None:
        self.failures = 0
        self.blocked_until = 0.0

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures < self.failure_threshold:
            return

        # Exponential backoff: base * 2^(k), capped
        k = self.failures - self.failure_threshold
        delay = min(self.backoff_max_s, self.backoff_base_s * (2.0**k))
        self.blocked_until = self._now() + float(delay)

    def call(self, fn: Callable[[], T]) -> T:
        """Call ``fn`` if allowed, else raise CircuitBreakerError."""

        if not self.can_call():
            wait = self.backoff_remaining_s()
            if wait > 0:
                raise CircuitBreakerError(f"{self.name}: circuit open for {wait:.2f}s")
            wait_bucket = self.bucket.wait_time_s(1.0)
            raise CircuitBreakerError(f"{self.name}: rate limited, retry in {wait_bucket:.2f}s")

        try:
            out = fn()
        except Exception:
            self.record_failure()
            raise
        else:
            self.record_success()
            return out
