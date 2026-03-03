"""engine.core.novelty

Novelty penalty: suppress confidence when a producer's forecast agrees
with existing brain conviction without adding new information.

"Brain is already 0.75 bullish on BTC. Am I adding signal or noise?"

Rules:
- High agreement + high existing conviction → suppress (low novelty)
- Disagreement with conviction → preserve or boost slightly (contrarian = information)
- Conviction near zero → no penalty (brain is uncertain, all signals valuable)

Novelty penalty is applied AFTER interpretation, BEFORE emit.
Action is NEVER changed directly — only confidence is modulated.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.brain.conviction_state import _DIRECTION_SIGN

# Tuning constants
NOVELTY_CONVICTION_THRESHOLD = 0.5
NOVELTY_AGREEMENT_PENALTY = 0.15
NOVELTY_CONTRARIAN_BOOST = 0.05
NOVELTY_MIN_CONFIDENCE = 0.1


@dataclass(frozen=True, slots=True)
class NoveltyResult:
    confidence_delta: float  # signed adjustment to apply
    applied: bool
    reason: str
    brain_conviction: float  # the aggregate conviction seen
    agreement: float  # -1=full disagreement, +1=full agreement


def compute_novelty_penalty(
    *,
    candidate_action: str,
    candidate_confidence: float,
    brain_conviction: float,
) -> NoveltyResult:
    """Compute novelty-based confidence adjustment.

    Never changes action. Only modulates confidence.
    Returns NoveltyResult with confidence_delta to apply.
    """

    candidate_sign = _DIRECTION_SIGN.get(str(candidate_action).lower(), 0.0)
    if candidate_sign == 0.0:
        return NoveltyResult(
            confidence_delta=0.0,
            applied=False,
            reason="abstention_pass_through",
            brain_conviction=brain_conviction,
            agreement=0.0,
        )

    agreement = float(candidate_sign * brain_conviction)
    conviction_strength = abs(float(brain_conviction))

    if conviction_strength < NOVELTY_CONVICTION_THRESHOLD:
        return NoveltyResult(
            confidence_delta=0.0,
            applied=False,
            reason="brain_conviction_weak",
            brain_conviction=brain_conviction,
            agreement=agreement,
        )

    if agreement > 0.3:
        # Agreeing with strong conviction → low novelty → penalize.
        penalty = NOVELTY_AGREEMENT_PENALTY * agreement * conviction_strength
        penalty_cap = max(float(candidate_confidence) - NOVELTY_MIN_CONFIDENCE, 0.0)
        delta = -round(min(penalty, penalty_cap), 4)
        return NoveltyResult(
            confidence_delta=delta,
            applied=True,
            reason=f"low_novelty agreement={agreement:.2f} conviction={brain_conviction:.2f}",
            brain_conviction=brain_conviction,
            agreement=agreement,
        )

    if agreement < -0.3:
        # Disagreeing with strong conviction → contrarian signal → small boost.
        boost = NOVELTY_CONTRARIAN_BOOST * abs(agreement) * conviction_strength
        delta = round(boost, 4)
        return NoveltyResult(
            confidence_delta=delta,
            applied=True,
            reason=f"contrarian_signal agreement={agreement:.2f} conviction={brain_conviction:.2f}",
            brain_conviction=brain_conviction,
            agreement=agreement,
        )

    return NoveltyResult(
        confidence_delta=0.0,
        applied=False,
        reason="neutral_agreement",
        brain_conviction=brain_conviction,
        agreement=agreement,
    )
