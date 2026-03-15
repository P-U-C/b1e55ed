"""Scenario 4: High magnitude bullish signal → Long position opens.

Expected outcome: Long position is opened.
"""

SCENARIO = {
    "id": 4,
    "label": "high_magnitude_bullish_long_opens",
    "asset": "BTC",
    "entry_price": 95000.0,
    "price_series": [95000.0] * 10,
    "signal_inputs": {
        # Very strong bullish signals across all domains
        "SIGNAL_TA_V1": {
            "symbol": "BTC",
            "rsi_14": 22.0,  # deeply oversold
            "trend_strength": 0.95,
            "volume_ratio": 3.0,
        },
        "SIGNAL_ONCHAIN_V1": {
            "symbol": "BTC",
            "whale_netflow": 500.0,  # massive whale buying
            "exchange_flow": -300.0,  # coins leaving exchanges
            "price_momentum_24h": 9.5,
        },
        "SIGNAL_CURATOR_V1": {
            "symbol": "BTC",
            "conviction": 10.0,  # maximum conviction
            "direction": "bullish",
        },
        "SIGNAL_TRADFI_V1": {
            "symbol": "BTC",
            "funding_annualized": 10.0,  # optimal funding
            "basis_annualized": 5.0,  # optimal basis
            "oi_change_pct": 20.0,
        },
        "SIGNAL_SOCIAL_V1": {
            "symbol": "BTC",
            "score": 8.0,  # very positive sentiment
            "source_count": 50,
        },
    },
    "expected_outcome": {
        "position_opens": True,
        "position_direction": "long",
    },
}
