"""engine.core.client

Shared HTTP client with:
- rate limiting (token bucket)
- retries (exponential backoff)
- simple circuit breaker

The goal is uniform behavior across producers.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx

from engine.security.ssrf import check_url


@dataclass(frozen=True, slots=True)
class ClientConfig:
    rate_limit_rps: float = 1.0
    max_retries: int = 3
    timeout_s: float = 20.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_cooldown_s: float = 30.0


class _TokenBucket:
    def __init__(self, rate_per_sec: float) -> None:
        self.rate = max(rate_per_sec, 0.001)
        self.capacity = 1.0
        self.tokens = 1.0
        self.updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.updated_at
            self.updated_at = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
            # wait for enough tokens
            needed = 1.0 - self.tokens
            wait_s = needed / self.rate
        await asyncio.sleep(wait_s)
        # recurse once after sleep
        await self.acquire()


class CircuitBreaker:
    def __init__(self, threshold: int, cooldown_s: float) -> None:
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.failures = 0
        self.opened_at: float | None = None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        if (time.monotonic() - self.opened_at) >= self.cooldown_s:
            self.failures = 0
            self.opened_at = None
            return True
        return False

    def on_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def on_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()


class DataClient:
    def __init__(self, config: ClientConfig | None = None) -> None:
        self.config = config or ClientConfig()
        self._bucket = _TokenBucket(self.config.rate_limit_rps)
        self._breaker = CircuitBreaker(
            threshold=self.config.circuit_breaker_threshold,
            cooldown_s=self.config.circuit_breaker_cooldown_s,
        )
        self._client = httpx.AsyncClient(timeout=self.config.timeout_s)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        check = check_url(url)
        if not check.allowed:
            raise httpx.UnsupportedProtocol(f"blocked_url ({check.reason})")

        if not self._breaker.allow():
            raise httpx.TransportError("circuit breaker open")

        await self._bucket.acquire()

        last_exc: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                resp = await self._client.request(method, url, **kwargs)
                resp.raise_for_status()
                self._breaker.on_success()
                return resp
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as e:
                last_exc = e
                self._breaker.on_failure()
                if attempt >= self.config.max_retries:
                    break
                await asyncio.sleep(min(2**attempt, 8))

        assert last_exc is not None
        raise last_exc
