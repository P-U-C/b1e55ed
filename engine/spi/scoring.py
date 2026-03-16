"""Brier-based karma scoring — pure functions, no DB, no side effects."""


def compute_brier(confidence: float, outcome: bool) -> float:
    """Brier score component for a single conviction.

    Returns 0 for a perfect prediction, 1 for the worst possible prediction.
    Lower is better.
    """
    return (confidence - (1.0 if outcome else 0.0)) ** 2


def compute_karma_delta(
    current_karma: float,
    epoch_brier: float,
    smoothing_factor: float = 0.70,
) -> float:
    """Karma update from epoch Brier score. Returns delta (new - old).

    Applies exponential smoothing: new = 0.7 * old + 0.3 * epoch_karma
    Clamps result to [0.0, 1.0].
    """
    epoch_karma = 1.0 - epoch_brier
    new_karma = (smoothing_factor * current_karma) + ((1.0 - smoothing_factor) * epoch_karma)
    new_karma = max(0.0, min(1.0, new_karma))
    return new_karma - current_karma


def determine_direction_correct(direction: str, price_change_pct: float) -> bool:
    """Was the directional claim correct given the actual price change?

    - bullish: correct if price went up (> 0%)
    - bearish: correct if price went down (< 0%)
    - neutral: correct if price moved < 2% either way
    """
    if direction == "bullish":
        return price_change_pct > 0
    elif direction == "bearish":
        return price_change_pct < 0
    else:  # neutral
        return abs(price_change_pct) < 2.0  # within 2% = neutral correct
