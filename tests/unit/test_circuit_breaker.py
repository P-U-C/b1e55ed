from __future__ import annotations

import pytest

from engine.execution.circuit_breaker import CircuitBreaker, CircuitBreakerError, TokenBucket


def test_token_bucket_rate_limits() -> None:
    bucket = TokenBucket(capacity=2, refill_rate_per_s=1.0)
    br = CircuitBreaker(name="venue", bucket=bucket, failure_threshold=3)

    # take two immediate calls
    assert br.can_call(now=0.0) is True
    assert br.can_call(now=0.0) is True
    # third should be limited
    assert br.can_call(now=0.0) is False

    # after 1 second, one token refills
    assert br.can_call(now=1.0) is True


def test_exponential_backoff_opens_after_failures() -> None:
    bucket = TokenBucket(capacity=10, refill_rate_per_s=10.0)
    br = CircuitBreaker(name="venue", bucket=bucket, failure_threshold=2, backoff_base_s=1.0, backoff_max_s=10.0)

    # record two failures -> backoff window starts
    br.record_failure()
    assert br.backoff_remaining_s(now=0.0) == 0.0

    br.record_failure()
    assert br.backoff_remaining_s(now=0.0) > 0.0
    assert br.can_call(now=0.0) is False


def test_call_raises_when_limited() -> None:
    bucket = TokenBucket(capacity=1, refill_rate_per_s=0.0001)
    br = CircuitBreaker(name="venue", bucket=bucket)

    # Use real monotonic time so we don't accidentally grant a huge refill window.
    br.bucket.try_take(1.0)

    with pytest.raises(CircuitBreakerError):
        br.call(lambda: 123)
