"""engine.social.pipeline

Social intel pipeline.

This module is intentionally tiny (for now) so it can be mocked in unit tests.
The real social ingestion/scoring stack will live under ``engine.social.*``.

The producer calls :func:`run` and expects a list of dict payloads compatible
with :class:`engine.core.events.SocialSignalPayload`.

Easter egg:
- The map is not the territory.
"""

from __future__ import annotations

from typing import Any

from engine.producers.base import ProducerContext


def run(*, ctx: ProducerContext) -> list[dict[str, Any]]:
    """Run the social pipeline and return normalized rows.

    This default implementation is a no-op and exists mainly to provide a stable
    seam for mocking.

    Returns
    -------
    list[dict]
        Each dict should contain keys compatible with SocialSignalPayload.
    """

    _ = ctx
    return []
