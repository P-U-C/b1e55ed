"""Scenario 2: ETH short signal, price rises above stop.

Expected outcome: Position auto-closes at stop (loss).
"""

SCENARIO = {
    "id": 2,
    "label": "eth_short_hits_stop",
    "asset": "ETH",
    "entry_price": 3000.0,
    "take_profit_pct": 0.08,  # -8% (price drops)
    "stop_loss_pct": 0.05,  # +5% (price rises — stop for short)
    "take_profit_price": 2760.0,  # 3000 * 0.92
    "stop_loss_price": 3150.0,  # 3000 * 1.05
    "price_series": [
        3000.0,
        3020.0,
        3040.0,
        3060.0,
        3080.0,
        3100.0,
        3120.0,
        3155.0,
        3200.0,
        3250.0,  # step 7 hits stop for short
    ],
    "signal_inputs": {
        # Strong bearish signals
        "SIGNAL_TA_V1": {
            "symbol": "ETH",
            "rsi_14": 80.0,  # overbought → bearish
            "trend_strength": -0.8,
            "volume_ratio": 0.3,
        },
        "SIGNAL_ONCHAIN_V1": {
            "symbol": "ETH",
            "whale_netflow": -300.0,  # large outflow → bearish
            "exchange_flow": 200.0,  # exchange inflow → selling pressure
            "price_momentum_24h": -9.0,
        },
        "SIGNAL_CURATOR_V1": {
            "symbol": "ETH",
            "conviction": 8.5,
            "direction": "bearish",
        },
        "SIGNAL_TRADFI_V1": {
            "symbol": "ETH",
            "funding_annualized": 50.0,  # high funding → crowded longs → bearish
            "basis_annualized": 15.0,
            "oi_change_pct": -20.0,
        },
    },
    "expected_outcome": {
        "position_direction": "short",
        "closes_at_stop_loss": True,
        "realized_pnl_negative": True,  # stop hit = loss
    },
}
