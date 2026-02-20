"""engine.backtest.stats

Statistical testing helpers for backtests (B1c).

This is not academic finance. It's a guardrail:
- p-value via simple bootstrap against a null of zero-mean returns
- FDR correction (Benjamini–Hochberg)

If the test says 'noise', treat it as noise.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class TestResult:
    statistic: float
    p_value: float


def bootstrap_p_value_mean_gt_zero(
    returns: np.ndarray,
    *,
    n_boot: int = 2000,
    seed: int = 0,
) -> TestResult:
    """Bootstrap p-value for mean(returns) > 0.

    Null: mean == 0. Uses sign-flip bootstrap.
    """

    r = returns.astype(np.float64)
    if r.size < 5:
        return TestResult(statistic=float(np.mean(r) if r.size else 0.0), p_value=1.0)

    rng = np.random.default_rng(int(seed))
    obs = float(np.mean(r))

    # sign-flip: symmetric around 0
    flips = rng.choice([-1.0, 1.0], size=(n_boot, r.size))
    sims = np.mean(flips * r[None, :], axis=1)
    p = float((np.sum(sims >= obs) + 1.0) / (n_boot + 1.0))
    return TestResult(statistic=obs, p_value=p)


def benjamini_hochberg(p_values: list[float], *, q: float = 0.05) -> list[bool]:
    """Return boolean mask of discoveries under BH-FDR."""

    if not p_values:
        return []
    m = len(p_values)
    pv = np.array(p_values, dtype=np.float64)
    order = np.argsort(pv)
    thresh = q * (np.arange(1, m + 1) / m)
    passed = pv[order] <= thresh
    if not np.any(passed):
        return [False] * m

    k = int(np.max(np.where(passed)[0]))
    cutoff = float(pv[order][k])
    return [float(p) <= cutoff for p in p_values]
