"""engine.execution.dynamic_kelly

Dynamic Kelly criterion — learn p and b from realized trade history.

Static Kelly (p=0.55, b=1.2) is worse than useless across regime transitions.
This module computes Kelly inputs from actual closed positions, with:

- Configurable lookback window (default: last 50 trades)
- Bayesian prior to prevent extreme sizing on small samples
- Minimum sample requirement before overriding defaults
- Optional per-asset and per-strategy breakdown
- Decay weighting (recent trades matter more)

Usage::

    from engine.execution.dynamic_kelly import DynamicKelly

    dk = DynamicKelly(db)
    params = dk.compute()  # returns KellyParams
    sizer = PositionSizer(kelly=params)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.core.database import Database
from engine.execution.position_sizer import KellyParams


@dataclass(frozen=True, slots=True)
class DynamicKellyConfig:
    """Configuration for dynamic Kelly computation."""

    lookback: int = 50  # max trades to consider
    min_trades: int = 10  # below this, use prior
    prior_p: float = 0.50  # Bayesian prior win rate (conservative)
    prior_b: float = 1.0  # Bayesian prior payoff ratio (break-even)
    prior_weight: int = 5  # equivalent pseudo-observations for prior
    fraction_multiplier: float = 0.5  # half-Kelly by default
    decay_halflife: int | None = 20  # exponential decay halflife in trades (None = no decay)
    min_p_for_betting: float = 0.35  # below this, Kelly = 0 (don't bet)


@dataclass(frozen=True, slots=True)
class KellyEstimate:
    """Full estimation result with diagnostics."""

    p: float  # estimated win probability
    b: float  # estimated payoff ratio (avg_win / avg_loss)
    n_trades: int  # number of trades used
    n_wins: int
    n_losses: int
    avg_win_usd: float
    avg_loss_usd: float
    used_prior: bool  # True if sample too small, fell back to prior blend
    kelly_fraction: float  # raw Kelly fraction (before half-Kelly)
    params: KellyParams  # ready to use


class DynamicKelly:
    """Compute Kelly parameters from realized trade history."""

    def __init__(self, db: Database, config: DynamicKellyConfig | None = None) -> None:
        self.db = db
        self.config = config or DynamicKellyConfig()

    def _fetch_closed_trades(
        self,
        *,
        asset: str | None = None,
    ) -> list[dict[str, object]]:
        """Fetch closed positions with realized PnL, newest first."""
        query = "SELECT realized_pnl, closed_at FROM positions WHERE status = 'closed' AND realized_pnl IS NOT NULL"
        params_list: list[str] = []
        if asset is not None:
            query += " AND UPPER(asset) = ?"
            params_list.append(asset.upper())

        query += " ORDER BY closed_at DESC"
        if self.config.lookback > 0:
            query += f" LIMIT {int(self.config.lookback)}"

        rows = self.db.fetchall(query, params_list)
        # Return in chronological order (oldest first) for decay weighting
        return [{"pnl": float(r[0]), "closed_at": str(r[1])} for r in reversed(rows)]

    def compute(
        self,
        *,
        asset: str | None = None,
    ) -> KellyParams:
        """Compute dynamic Kelly params from trade history.

        Returns KellyParams ready for PositionSizer.
        """
        return self.estimate(asset=asset).params

    def estimate(
        self,
        *,
        asset: str | None = None,
    ) -> KellyEstimate:
        """Full estimation with diagnostics."""
        trades = self._fetch_closed_trades(asset=asset)
        pnls = np.array([t["pnl"] for t in trades], dtype=np.float64)

        n_trades = len(pnls)
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]  # negative values
        n_wins = int(wins.shape[0])
        n_losses = int(losses.shape[0])

        avg_win = float(np.mean(wins)) if n_wins > 0 else 0.0
        avg_loss = float(np.mean(np.abs(losses))) if n_losses > 0 else 0.0

        cfg = self.config

        if n_trades < cfg.min_trades:
            # Blend with prior (Bayesian smoothing)
            p, b = self._blend_with_prior(n_wins, n_losses, avg_win, avg_loss, n_trades=n_trades)
            used_prior = True
        else:
            # Enough data — compute with optional decay weighting
            if cfg.decay_halflife is not None and n_trades > 1:
                p, b = self._decay_weighted(pnls)
            else:
                p = n_wins / n_trades if n_trades > 0 else cfg.prior_p
                b = avg_win / avg_loss if avg_loss > 0 else cfg.prior_b
            used_prior = False

        # Safety floor — zero out both kelly_fraction AND params.fraction_multiplier
        # so any caller using compute() → PositionSizer(kelly=params) also gets zero.
        below_floor = p < cfg.min_p_for_betting
        if below_floor:
            kelly_f = 0.0
        else:
            q = 1.0 - p
            kelly_f = max(0.0, (b * p - q) / b)

        params = KellyParams(
            p=p,
            b=b,
            fraction_multiplier=0.0 if below_floor else cfg.fraction_multiplier,
        )

        return KellyEstimate(
            p=p,
            b=b,
            n_trades=n_trades,
            n_wins=n_wins,
            n_losses=n_losses,
            avg_win_usd=avg_win,
            avg_loss_usd=avg_loss,
            used_prior=used_prior,
            kelly_fraction=kelly_f,
            params=params,
        )

    def _blend_with_prior(
        self,
        n_wins: int,
        n_losses: int,
        avg_win: float,
        avg_loss: float,
        *,
        n_trades: int | None = None,
    ) -> tuple[float, float]:
        """Bayesian blending with prior for small sample sizes.

        ``n_trades`` is used as the denominator for the win-rate blend so that
        flat trades (``realized_pnl == 0``) are counted consistently with the
        non-prior branch.  Falls back to ``n_wins + n_losses`` when not supplied
        for backward compatibility.
        """
        cfg = self.config
        pw = int(cfg.prior_weight)
        # Use n_trades (includes flat trades) for consistency with non-prior branch
        n_total = n_trades if n_trades is not None else (n_wins + n_losses)

        # Blended win rate: (prior_wins + actual_wins) / (prior_total + actual_total)
        prior_wins = cfg.prior_p * pw
        p = (prior_wins + n_wins) / (pw + n_total) if (pw + n_total) > 0 else cfg.prior_p

        # Blended payoff ratio (use n_wins+n_losses for payoff — flat trades carry no info)
        n_wl = n_wins + n_losses
        if avg_loss > 0 and avg_win > 0:
            actual_b = avg_win / avg_loss
            b = (cfg.prior_b * pw + actual_b * n_wl) / (pw + n_wl)
        else:
            b = cfg.prior_b

        return (p, b)

    def _decay_weighted(self, pnls: np.ndarray) -> tuple[float, float]:
        """Exponential decay weighting — recent trades matter more."""
        cfg = self.config
        n = pnls.shape[0]
        halflife = cfg.decay_halflife or n
        # Weights: most recent trade gets highest weight
        indices = np.arange(n, dtype=np.float64)
        weights = np.exp(np.log(2.0) * indices / halflife)
        weights /= weights.sum()

        # Weighted win rate
        is_win = (pnls > 0).astype(np.float64)
        p = float(np.dot(weights, is_win))

        # Weighted payoff ratio — conditional means (wins-only / losses-only)
        # Using unconditional means would double-count win-rate effects into b.
        win_mask = pnls > 0
        loss_mask = pnls < 0

        win_weights = weights[win_mask]
        loss_weights = weights[loss_mask]
        win_amounts = pnls[win_mask]
        loss_amounts = np.abs(pnls[loss_mask])

        if win_weights.sum() > 0 and loss_weights.sum() > 0:
            cond_avg_win = float(np.dot(win_weights, win_amounts) / win_weights.sum())
            cond_avg_loss = float(np.dot(loss_weights, loss_amounts) / loss_weights.sum())
            b = cond_avg_win / cond_avg_loss if cond_avg_loss > 0 else self.config.prior_b
        else:
            b = self.config.prior_b

        return (p, b)
