"""engine.backtest.io

Lightweight IO helpers for backtesting.

CSV schema:
- required: close
- optional: high, low, volume

All columns must be numeric.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True, slots=True)
class PriceSeries:
    close: np.ndarray
    high: np.ndarray | None = None
    low: np.ndarray | None = None
    volume: np.ndarray | None = None


def load_prices_csv(path: str | Path) -> PriceSeries:
    p = Path(path)
    rows: list[dict[str, str]] = []
    with p.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append({k.strip(): (v.strip() if isinstance(v, str) else "") for k, v in row.items() if k is not None})

    if not rows:
        return PriceSeries(close=np.zeros(0, dtype=np.float64))

    def col(name: str) -> np.ndarray | None:
        if name not in rows[0]:
            return None
        out: list[float] = []
        for row in rows:
            v = row.get(name, "")
            if v is None or v == "":
                out.append(float("nan"))
            else:
                out.append(float(v))
        return np.array(out, dtype=np.float64)

    close = col("close")
    if close is None:
        raise ValueError("CSV missing required column: close")

    return PriceSeries(close=close, high=col("high"), low=col("low"), volume=col("volume"))
