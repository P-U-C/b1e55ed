"""Scenario 5: High magnitude bearish signal → Short position opens.

Expected outcome: Short position is opened.
"""

SCENARIO = {
    "id": 5,
    "label": "high_magnitude_bearish_short_opens",
    "asset": "ETH",
    "entry_price": 3000.0,
    "price_series": [3000.0] * 10,
    "signal_inputs": {
        # Very strong bearish signals
        "SIGNAL_TA_V1": {
            "symbol": "ETH",
            "rsi_14": 82.0,  # deeply overbought
            "trend_strength": -0.9,
            "volume_ratio": 0.2,
        },
        "SIGNAL_ONCHAIN_V1": {
            "symbol": "ETH",
            "whale_netflow": -600.0,  # massive whale selling
            "exchange_flow": 400.0,  # heavy exchange inflow
            "price_momentum_24h": -9.5,
        },
        "SIGNAL_CURATOR_V1": {
            "symbol": "ETH",
            "conviction": 10.0,
            "direction": "bearish",
        },
        "SIGNAL_TRADFI_V1": {
            "symbol": "ETH",
            "funding_annualized": 80.0,  # very high funding → crowded longs
            "basis_annualized": 20.0,
            "oi_change_pct": -30.0,
        },
        "SIGNAL_SOCIAL_V1": {
            "symbol": "ETH",
            "score": -8.0,  # very negative sentiment
            "source_count": 50,
        },
    },
    "expected_outcome": {
        "position_opens": True,
        "position_direction": "short",
    },
}
