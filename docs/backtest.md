---
title: "Backtest Engine"
description: "Walk-forward validation, grid sweep, and regime-conditioned backtesting."
---

# Backtest Engine

b1e55ed includes a walk-forward backtesting engine for strategy validation.

## Commands

### Walk-forward

```bash
b1e55ed backtest walkforward \
  --symbols BTC,ETH,SOL \
  --strategies momentum,ma_crossover \
  --start 2023-01-01 \
  --end 2025-12-31
```

Runs a walk-forward test with FDR-corrected results. Outputs: Sharpe ratio, Sortino ratio, max drawdown, win rate per strategy/asset combination.

### Grid sweep

```bash
b1e55ed backtest gridsweep \
  --strategies momentum \
  --assets BTC,ETH
```

Sweeps parameter combinations for a strategy. FDR correction applied across all combinations to control false discovery rate.

### Mega sweep

```bash
b1e55ed backtest megasweep
```

Sweeps all strategies × all parameter combos × all assets. Runs in parallel. Produces ranked survivors after FDR correction.

### Regime-conditioned

```bash
b1e55ed backtest regime --symbols BTC,ETH
```

Breaks performance down by detected regime (EARLY_BULL, LATE_BULL, BEAR, SIDEWAYS). Shows which strategies hold in each regime.

## Dynamic Kelly

```bash
b1e55ed kelly
```

Estimates optimal position sizing from trade history using the Kelly criterion. Regime-adjusted.

## Understanding results

| Metric | Threshold | Notes |
|--------|-----------|-------|
| Sharpe > 0.5 | Acceptable | After costs |
| Sharpe > 1.0 | Good | Reproducible edge |
| Max DD < 25% | Acceptable | Strategy-dependent |
| Passes FDR q=0.05 | Required | Controls false discoveries |

FDR correction is mandatory. A strategy that looks good on a single backtest is likely noise.

## Key findings

Combined multi-factor strategies (momentum + MA crossover) outperform single-factor strategies after FDR correction. Pure momentum and pure RSI do not survive strict out-of-sample validation.

See: [architecture.md](architecture.md) for how backtest results feed into the learning loop.
