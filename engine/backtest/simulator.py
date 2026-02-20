"""engine.backtest.simulator

Single-asset backtest simulator.

This is intentionally minimal but correct:
- position determined by signal (-1..+1)
- daily/period returns applied with transaction costs when position changes

No leverage, no funding, no slippage model beyond fixed bps.
Those can be layered later.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class SimConfig:
    fee_bps: float = 10.0  # 0.10% per position change notional


@dataclass(frozen=True, slots=True)
class SimResult:
    equity: np.ndarray  # (T,)
    returns: np.ndarray  # (T,)
    position: np.ndarray  # (T,)
    fees: np.ndarray  # (T,)


def simulate(*, close: np.ndarray, signal: np.ndarray, cfg: SimConfig | None = None) -> SimResult:
    cfg = cfg or SimConfig()

    close = close.astype(np.float64)
    signal = np.clip(signal.astype(np.float64), -1.0, 1.0)

    if close.ndim != 1 or signal.ndim != 1 or close.shape[0] != signal.shape[0]:
        raise ValueError("close and signal must be 1D arrays of same length")

    t_len = close.shape[0]
    if t_len == 0:
        return SimResult(
            equity=np.zeros(0, dtype=np.float64),
            returns=np.zeros(0, dtype=np.float64),
            position=np.zeros(0, dtype=np.float64),
            fees=np.zeros(0, dtype=np.float64),
        )

    # Compute bar returns (simple)
    ret = np.zeros(t_len, dtype=np.float64)
    ret[1:] = (close[1:] / close[:-1]) - 1.0

    pos = signal.copy()

    # Fees when position changes
    fees = np.zeros(t_len, dtype=np.float64)
    turnover = np.abs(np.diff(pos, prepend=pos[0]))
    # If you go 0 -> 1, turnover=1; 1 -> -1, turnover=2.
    fees = turnover * (cfg.fee_bps / 10_000.0)

    strat_ret = pos * ret - fees

    equity = np.ones(t_len, dtype=np.float64)
    for t in range(1, t_len):
        equity[t] = equity[t - 1] * (1.0 + strat_ret[t])

    return SimResult(equity=equity, returns=strat_ret, position=pos, fees=fees)
