from __future__ import annotations

import pytest

from engine.core.exceptions import (
    B1e55edError,
    ConfigError,
    DedupeConflictError,
    EventStoreError,
    InsufficientBalanceError,
    KillSwitchError,
    PreflightError,
    ProducerError,
    SecurityError,
)


def test_exception_hierarchy_is_structural() -> None:
    assert issubclass(ConfigError, B1e55edError)
    assert issubclass(EventStoreError, B1e55edError)
    assert issubclass(ProducerError, B1e55edError)
    assert issubclass(KillSwitchError, B1e55edError)
    assert issubclass(PreflightError, B1e55edError)
    assert issubclass(SecurityError, B1e55edError)


def test_error_message_you_are_not_a_whale_act_accordingly() -> None:
    with pytest.raises(InsufficientBalanceError) as e:
        raise InsufficientBalanceError("You are not a whale. Act accordingly.")
    assert "not a whale" in str(e.value)


def test_dedupe_conflict_is_event_store_error() -> None:
    assert issubclass(DedupeConflictError, EventStoreError)
