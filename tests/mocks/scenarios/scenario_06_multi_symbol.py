"""Scenario 6: Multiple symbols simultaneously (BTC+ETH+SOL).

Expected outcome: No deduplication errors, all positions tracked correctly.
"""

SCENARIO = {
    "id": 6,
    "label": "multi_symbol_btc_eth_sol",
    "assets": ["BTC", "ETH", "SOL"],
    "entry_prices": {
        "BTC": 95000.0,
        "ETH": 3000.0,
        "SOL": 180.0,
    },
    "price_series": {
        "BTC": [95000.0] * 5,
        "ETH": [3000.0] * 5,
        "SOL": [180.0] * 5,
    },
    "signal_inputs": {
        "BTC": {
            "SIGNAL_TA_V1": {"symbol": "BTC", "rsi_14": 25.0, "trend_strength": 0.9},
            "SIGNAL_CURATOR_V1": {"symbol": "BTC", "conviction": 9.0, "direction": "bullish"},
            "SIGNAL_ONCHAIN_V1": {"symbol": "BTC", "whale_netflow": 400.0, "exchange_flow": -200.0, "price_momentum_24h": 8.0},
        },
        "ETH": {
            "SIGNAL_TA_V1": {"symbol": "ETH", "rsi_14": 27.0, "trend_strength": 0.88},
            "SIGNAL_CURATOR_V1": {"symbol": "ETH", "conviction": 8.5, "direction": "bullish"},
            "SIGNAL_ONCHAIN_V1": {"symbol": "ETH", "whale_netflow": 300.0, "exchange_flow": -150.0, "price_momentum_24h": 7.5},
        },
        "SOL": {
            "SIGNAL_TA_V1": {"symbol": "SOL", "rsi_14": 23.0, "trend_strength": 0.92},
            "SIGNAL_CURATOR_V1": {"symbol": "SOL", "conviction": 9.5, "direction": "bullish"},
            "SIGNAL_ONCHAIN_V1": {"symbol": "SOL", "whale_netflow": 200.0, "exchange_flow": -100.0, "price_momentum_24h": 9.0},
        },
    },
    "expected_outcome": {
        "all_positions_open": True,
        "position_count": 3,
        "no_deduplication_errors": True,
        "symbols_with_positions": ["BTC", "ETH", "SOL"],
    },
}
