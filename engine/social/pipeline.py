"""engine.social.pipeline

Social intel pipeline orchestrator.

Collects from all available sources, filters, scores, and returns
list[dict] compatible with SocialSignalPayload.

The producer calls ``run(ctx=self.ctx)`` and trusts the output.
"""

from __future__ import annotations

import logging
from typing import Any

from engine.producers.base import ProducerContext
from engine.social.collectors.base import BaseCollector
from engine.social.collectors.fear_greed import FearGreedCollector
from engine.social.collectors.polymarket import PolymarketCollector
from engine.social.collectors.reddit import RedditCollector
from engine.social.collectors.trends import TrendsCollector
from engine.social.filters.echo_chamber import detect_echo_chamber
from engine.social.filters.preprocessing import preprocess
from engine.social.scoring.aggregator import aggregate
from engine.social.scoring.contrarian import apply_contrarian_signals

logger = logging.getLogger(__name__)


def _build_collectors() -> list[BaseCollector]:
    """Build the list of active collectors."""
    return [
        FearGreedCollector(),
        PolymarketCollector(),
        RedditCollector(),
        TrendsCollector(),
    ]


def run(*, ctx: ProducerContext) -> list[dict[str, Any]]:
    """Run the social pipeline and return normalized rows.

    Returns
    -------
    list[dict]
        Each dict contains keys compatible with SocialSignalPayload:
        symbol, score, direction, source_count, contrarian_flag, echo_chamber_flag
    """
    symbols = [s.upper().strip() for s in ctx.config.universe.symbols]
    if not symbols:
        logger.warning("social_pipeline_no_symbols")
        return []

    # ── Collect from all sources ──
    collectors = _build_collectors()
    raw: list[dict[str, Any]] = []

    for collector in collectors:
        try:
            data = collector.collect(symbols)
            if data:
                raw.extend(data)
                logger.info(
                    "social_collector_ok",
                    extra={"collector": collector.name, "signals": len(data)},
                )
        except Exception:
            logger.warning(
                "social_collector_failed",
                extra={"collector": collector.name},
                exc_info=True,
            )

    if not raw:
        logger.info("social_pipeline_no_raw_data")
        return []

    # ── Filter ──
    filtered = preprocess(raw)
    filtered = detect_echo_chamber(filtered)

    # ── Score ──
    scored = aggregate(filtered, symbols)
    scored = apply_contrarian_signals(scored)

    logger.info("social_pipeline_complete", extra={"symbols_scored": len(scored), "raw_signals": len(raw)})
    return scored
