"""Scenario 3: Signal magnitude below threshold.

Expected outcome: NO trade opens (magnitude < auto_paper_trade_min_magnitude).
"""

SCENARIO = {
    "id": 3,
    "label": "below_threshold_no_trade",
    "asset": "BTC",
    "entry_price": 95000.0,
    "price_series": [95000.0] * 10,
    "signal_inputs": {
        # Weak/mixed signals — will result in low PCS near 50 → neutral direction
        "SIGNAL_TA_V1": {
            "symbol": "BTC",
            "rsi_14": 50.0,  # perfectly neutral RSI
            "trend_strength": 0.1,  # very weak trend
        },
        "SIGNAL_ONCHAIN_V1": {
            "symbol": "BTC",
            "whale_netflow": 2.0,  # near-zero flow
            "exchange_flow": -1.0,
            "price_momentum_24h": 0.1,
        },
        "SIGNAL_CURATOR_V1": {
            "symbol": "BTC",
            "conviction": 1.0,  # very low conviction
            "direction": "neutral",
        },
    },
    "expected_outcome": {
        "no_trade_opens": True,
        "reason": "magnitude_below_threshold",
    },
}
