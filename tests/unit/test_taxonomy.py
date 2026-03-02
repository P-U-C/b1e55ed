from __future__ import annotations

import logging

import pytest

from engine.brain.synthesis import VectorSynthesis
from engine.core.client import DataClient
from engine.core.config import Config
from engine.core.database import Database
from engine.core.metrics import MetricsRegistry
from engine.core.types import CANONICAL_DOMAINS, validate_domain
from engine.producers.base import BaseProducer, ProducerContext

EXPECTED_DOMAINS = {
    "technical",
    "onchain",
    "tradfi",
    "social",
    "events",
    "curator",
}


@pytest.fixture()
def mock_ctx(tmp_path) -> ProducerContext:  # type: ignore[no-untyped-def]
    db = Database(tmp_path / "events.db")
    return ProducerContext(
        config=Config(),
        db=db,
        client=DataClient(),
        metrics=MetricsRegistry(),
        logger=logging.getLogger("test"),
    )


def test_canonical_domains_has_exactly_six_entries() -> None:
    assert len(CANONICAL_DOMAINS) == 6


def test_canonical_domains_contains_expected_names() -> None:
    assert EXPECTED_DOMAINS.issubset(CANONICAL_DOMAINS)


def test_macro_not_in_canonical_domains() -> None:
    assert "macro" not in CANONICAL_DOMAINS


def test_validate_domain_accepts_technical() -> None:
    assert validate_domain("technical") == "technical"


def test_validate_domain_rejects_macro() -> None:
    with pytest.raises(ValueError, match="macro"):
        validate_domain("macro")


def test_validate_domain_accepts_curator() -> None:
    assert validate_domain("curator") == "curator"


def test_synthesis_domains_match_canonical_domains() -> None:
    assert sorted(CANONICAL_DOMAINS) == VectorSynthesis.DOMAINS


def test_base_producer_rejects_invalid_domain(mock_ctx: ProducerContext) -> None:
    class BadProducer(BaseProducer):
        name = "bad"
        domain = "macro"
        schedule = "*/15 * * * *"

        def collect(self) -> list[dict]:
            return []

        def normalize(self, raw: list[dict]):
            return []

    with pytest.raises(ValueError, match="macro"):
        BadProducer(ctx=mock_ctx)
