"""engine.core.regime — regime metadata available to all layers."""

from __future__ import annotations

from dataclasses import dataclass, field

# Confidence cap per regime (0-10 scale, converted to 0.0-1.0 at point of use).
# These are the canonical regime caps. engine.brain.conviction imports from here.
# Ashby would call this requisite variety: controls must match the market's regimes.
REGIME_CAPS: dict[str, float] = {
    "BULL": 10.0,
    "BEAR": 7.0,
    "TRANSITION": 6.0,
    "CRISIS": 4.0,
    # V2 regime labels (continuous detector)
    "LEAN_BULL": 10.0,
    "LEAN_BEAR": 8.0,
    "NEUTRAL": 8.0,
}


@dataclass(frozen=True)
class RegimeConfig:
    """Behavioural overrides for a single regime.

    All fields are optional — unset means "no change from default".
    """

    # Scale the rule-engine's candidate confidence before guardrails.
    # 1.0 = no change. 0.5 = halve confidence. 1.2 = boost 20%.
    confidence_multiplier: float = 1.0

    # If True, always abstain when this regime is active.
    # Overrides confidence_multiplier.
    abstain: bool = False

    # Named rule groups that are active in this regime.
    # None means "all rules active". frozenset([]) means "no rules run → implicit abstain".
    # Used by producers that have discrete named rule groups.
    active_rules: frozenset[str] | None = None

    # Minimum confidence to emit a non-abstention forecast in this regime.
    # None means "use the interpreter's default min_confidence".
    min_confidence: float | None = None


@dataclass
class RegimeMatrix:
    """Per-regime decision matrix for an interpreter.

    Declare once on the interpreter class. The base class applies it
    automatically after interpret() returns — no if/else inside rules.

    Example:
        matrix = RegimeMatrix(
            configs={
                "BULL": RegimeConfig(confidence_multiplier=1.1),
                "BEAR": RegimeConfig(confidence_multiplier=0.7, min_confidence=0.5),
                "CRISIS": RegimeConfig(abstain=True),
                "TRANSITION": RegimeConfig(confidence_multiplier=0.85),
            }
        )
    """

    configs: dict[str, RegimeConfig] = field(default_factory=dict)
    default: RegimeConfig = field(default_factory=RegimeConfig)

    def get(self, regime_tag: str) -> RegimeConfig:
        """Return config for *regime_tag*, falling back to default."""
        return self.configs.get(regime_tag.upper(), self.default)
