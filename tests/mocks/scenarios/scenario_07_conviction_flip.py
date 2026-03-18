"""Scenario 7: Conviction flips mid-position.

A long position is opened. Then signals flip bearish. The engine should
handle gracefully — no double-open, no crash.

Expected outcome: No crash, original position stays open (or closes gracefully).
"""

SCENARIO = {
    "id": 7,
    "label": "conviction_flip_mid_position",
    "asset": "BTC",
    "entry_price": 95000.0,
    "price_series": [95000.0] * 10,
    "initial_signals": {
        # Phase 1: Strong bullish — opens long
        "SIGNAL_TA_V1": {"symbol": "BTC", "rsi_14": 25.0, "trend_strength": 0.9},
        "SIGNAL_CURATOR_V1": {"symbol": "BTC", "conviction": 9.5, "direction": "bullish"},
        "SIGNAL_ONCHAIN_V1": {"symbol": "BTC", "whale_netflow": 400.0, "exchange_flow": -200.0, "price_momentum_24h": 8.0},
    },
    "flipped_signals": {
        # Phase 2: Strong bearish — conviction flips (tests engine graceful handling)
        "SIGNAL_TA_V1": {"symbol": "BTC", "rsi_14": 82.0, "trend_strength": -0.9},
        "SIGNAL_CURATOR_V1": {"symbol": "BTC", "conviction": 9.5, "direction": "bearish"},
        "SIGNAL_ONCHAIN_V1": {"symbol": "BTC", "whale_netflow": -400.0, "exchange_flow": 200.0, "price_momentum_24h": -8.0},
    },
    "expected_outcome": {
        "no_crash": True,
        "no_double_open": True,
        "initial_position_direction": "long",
    },
}
