"""Scenario 1: SOL long signal, price rises, hits take profit.

Expected outcome: Position auto-closes at target.
"""

SCENARIO = {
    "id": 1,
    "label": "sol_long_hits_tp",
    "asset": "SOL",
    "entry_price": 180.0,
    "take_profit_pct": 0.10,  # +10%
    "stop_loss_pct": 0.05,  # -5%
    "take_profit_price": 198.0,  # 180 * 1.10
    "stop_loss_price": 171.0,  # 180 * 0.95
    "price_series": [
        180.0,
        181.5,
        183.0,
        185.0,
        187.0,
        189.0,
        191.0,
        193.0,
        195.0,
        198.5,  # step 9 hits TP
    ],
    "signal_inputs": {
        # Strong bullish signals across multiple domains
        "SIGNAL_TA_V1": {
            "symbol": "SOL",
            "rsi_14": 28.0,  # oversold → bullish
            "trend_strength": 0.85,
            "volume_ratio": 2.5,
        },
        "SIGNAL_ONCHAIN_V1": {
            "symbol": "SOL",
            "whale_netflow": 250.0,  # massive inflow
            "exchange_flow": -150.0,  # outflow from exchanges
            "price_momentum_24h": 8.0,
        },
        "SIGNAL_CURATOR_V1": {
            "symbol": "SOL",
            "conviction": 9.5,
            "direction": "bullish",
        },
        "SIGNAL_TRADFI_V1": {
            "symbol": "SOL",
            "funding_annualized": 10.0,
            "basis_annualized": 5.0,
            "oi_change_pct": 15.0,
        },
    },
    "expected_outcome": {
        "position_direction": "long",
        "closes_at_take_profit": True,
        "realized_pnl_positive": True,
    },
}
