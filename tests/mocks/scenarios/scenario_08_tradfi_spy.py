"""Scenario 8: TradFi symbol (SPY) added to universe.

Expected outcome: Signals generate, no crash, position lifecycle works.
"""

SCENARIO = {
    "id": 8,
    "label": "tradfi_spy_universe",
    "asset": "SPY",
    "entry_price": 580.0,
    "price_series": [580.0, 582.0, 585.0, 589.0, 595.0],
    "signal_inputs": {
        # TradFi-domain signals for SPY
        "SIGNAL_TRADFI_V1": {
            "symbol": "SPY",
            "funding_annualized": 10.0,  # optimal TradFi funding
            "basis_annualized": 5.0,
            "oi_change_pct": 12.0,
            "meltup_score": 0.8,
        },
        "SIGNAL_CURATOR_V1": {
            "symbol": "SPY",
            "conviction": 8.0,
            "direction": "bullish",
        },
        "SIGNAL_TA_V1": {
            "symbol": "SPY",
            "rsi_14": 30.0,  # oversold
            "trend_strength": 0.8,
        },
        "SIGNAL_ONCHAIN_V1": {
            "symbol": "SPY",
            "whale_netflow": 200.0,
            "exchange_flow": -100.0,
            "price_momentum_24h": 5.0,
        },
    },
    "expected_outcome": {
        "no_crash": True,
        "signals_generate": True,
        "position_lifecycle_works": True,
    },
}
