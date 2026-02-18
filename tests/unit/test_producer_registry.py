from __future__ import annotations

import pytest

from engine.producers.base import BaseProducer
from engine.producers.registry import (
    _reset_for_tests,
    get_producer,
    list_by_domain,
    list_producers,
    register,
)


def test_register_and_get_producer() -> None:
    _reset_for_tests()

    @register("x", domain="technical")
    class X(BaseProducer):
        schedule = "continuous"

        def collect(self) -> list[dict]:
            return []

        def normalize(self, raw: list[dict]):
            return []

    assert get_producer("x") is X
    assert "x" in list_producers()
    assert list_by_domain("technical") == ["x"]


def test_duplicate_name_rejected() -> None:
    _reset_for_tests()

    @register("dup", domain="events")
    class A(BaseProducer):
        schedule = "continuous"

        def collect(self) -> list[dict]:
            return []

        def normalize(self, raw: list[dict]):
            return []

    with pytest.raises(ValueError):

        @register("dup", domain="events")
        class B(BaseProducer):
            schedule = "continuous"

            def collect(self) -> list[dict]:
                return []

            def normalize(self, raw: list[dict]):
                return []


def test_discovery_registers_template_producer() -> None:
    _reset_for_tests()
    names = list_producers()
    assert "template" in names
    assert "template" in list_by_domain("events")
