# TradFi Signals Pack

Traditional finance plumbing indicators for crypto market structure analysis.

---

## What's Included

1. **CME Basis Proxy** - Spot vs quarterly futures premium
2. **Funding Rate Monitor** - Perpetual swap funding extremes
3. **ETF Flow Tracker** - BTC/ETH ETF daily inflows/outflows

---

## Use Cases

### Crash Detection (@dgt10011 Framework)
Basis spike → TradFi deleveraging → BTC crash.

**Signal:** Basis jumps 3%+ in one day (e.g., 4% → 7%+)
**Interpretation:** Basis trade unwinding, margin calls cascading
**Action:** Reduce exposure, hedge, or wait for capitulation

**Example:** Feb 5-6, 2026 - Basis spiked 4% → 9%, BTC dumped $100K → $92K

### Melt-Up Detection
Basis optimal + funding healthy + ETF inflows = squeeze setup.

**Conditions:**
1. Basis 3-6% (TradFi re-leveraged but not crowded)
2. Funding positive <20% (longs paying but room to run)
3. ETF 3+ consecutive days inflows (fuel accumulating)
4. Open interest rising (new longs entering)

**Signal:** All 4 conditions met = melt-up score 4/4
**Action:** Size up for vertical move

### Risk-On/Risk-Off Regime
Funding + basis divergence reveals paper vs real money.

**Risk-On:** Funding positive + basis rising = real leverage
**Risk-Off:** Funding negative + basis falling = fear dominates
**Divergence:** Negative funding + ETF inflows = paper selling, real buying (buy signal)

---

## API Requirements

### CME Basis Proxy (Free)
- **Source:** Binance API (spot + quarterly futures)
- **Cost:** Free
- **Rate Limit:** 1200 req/min
- **Auth:** None required for public endpoints
- **Calculation:** `(quarterly_price - spot_price) / spot_price * 100 * (365 / days_to_expiry)`

### Funding Rates (Free)
- **Source:** Binance, Bybit, or Hyperliquid APIs
- **Cost:** Free
- **Rate Limit:** Varies by exchange
- **Auth:** None for public data
- **Data:** 8-hour funding rate (annualized = rate * 365 * 3)

### ETF Flows (Scraped)
- **Source:** Farside Investors (public website)
- **Cost:** Free
- **Rate Limit:** Reasonable scraping (once per day)
- **Auth:** None
- **Alternative:** Bloomberg Terminal (paid, requires subscription)

---

## Example: CME Basis Monitor

```python
"""Monitor BTC basis trade proxy (spot vs quarterly futures)."""
import requests
from datetime import datetime, timedelta
from b1e55ed.types import Signal

class CMEBasisProducer:
    def __init__(self, config: dict):
        self.api_base = "https://api.binance.com/api/v3"
        self.threshold_crowded = config.get("threshold_crowded", 8.0)  # 8%+ = crowded
        self.threshold_unwound = config.get("threshold_unwound", 2.0)  # <2% = unwound
    
    def produce(self, symbol: str) -> Signal:
        """Generate signal based on basis trade crowding."""
        if symbol != "BTC":
            return self._neutral(symbol, "Basis only tracked for BTC")
        
        try:
            basis_annual = self._calculate_basis()
            
            if basis_annual > self.threshold_crowded:
                return Signal(
                    symbol=symbol,
                    signal="short",  # Crowded = unwind risk
                    conviction=8,
                    rationale=f"CME basis crowded at {basis_annual:.1f}% (unwind risk)",
                    producer="CMEBasis",
                    timestamp=int(datetime.now().timestamp()),
                    metadata={"basis_annual": basis_annual, "status": "crowded"}
                )
            elif basis_annual < self.threshold_unwound:
                return Signal(
                    symbol=symbol,
                    signal="long",  # Unwound = safe to re-enter
                    conviction=6,
                    rationale=f"CME basis unwound at {basis_annual:.1f}% (stabilized)",
                    producer="CMEBasis",
                    timestamp=int(datetime.now().timestamp()),
                    metadata={"basis_annual": basis_annual, "status": "unwound"}
                )
            else:
                return self._neutral(
                    symbol, f"Basis neutral at {basis_annual:.1f}%"
                )
        
        except Exception as e:
            return self._neutral(symbol, f"Error: {str(e)}")
    
    def _calculate_basis(self) -> float:
        """Calculate annualized basis (spot vs quarterly futures)."""
        # Fetch spot price
        spot_url = f"{self.api_base}/ticker/price?symbol=BTCUSDT"
        spot_response = requests.get(spot_url, timeout=10)
        spot_price = float(spot_response.json()["price"])
        
        # Fetch quarterly futures price (next quarter)
        # Binance quarterly futures: BTCUSD_<YYMMDD> (e.g., BTCUSD_260328)
        # For simplicity, use fixed symbol or calculate next quarter
        futures_symbol = self._get_next_quarterly_symbol()
        futures_url = f"{self.api_base}/ticker/price?symbol={futures_symbol}"
        futures_response = requests.get(futures_url, timeout=10)
        futures_price = float(futures_response.json()["price"])
        
        # Calculate days to expiry (quarterly = ~90 days)
        days_to_expiry = 90  # Simplified
        
        # Annualized basis
        basis_pct = ((futures_price - spot_price) / spot_price) * 100
        basis_annual = basis_pct * (365 / days_to_expiry)
        
        return basis_annual
    
    def _get_next_quarterly_symbol(self) -> str:
        """Get next quarterly futures symbol."""
        # Binance quarterly contracts expire last Friday of Mar/Jun/Sep/Dec
        # For simplicity, return hardcoded (update quarterly)
        return "BTCUSD_260328"  # March 28, 2026
    
    def _neutral(self, symbol: str, rationale: str) -> Signal:
        return Signal(
            symbol=symbol,
            signal="neutral",
            conviction=0,
            rationale=rationale,
            producer="CMEBasis",
            timestamp=int(datetime.now().timestamp()),
            metadata={}
        )
```

**Config:**
```yaml
brain:
  producers:
    - name: cme_basis
      module: b1e55ed.producers.cme_basis
      class: CMEBasisProducer
      enabled: true
      config:
        threshold_crowded: 8.0   # Above this = short (unwind risk)
        threshold_unwound: 2.0   # Below this = long (re-leverage safe)
```

---

## Example: Funding Rate Extremes

```python
"""Track perpetual funding rate extremes."""
import requests
from b1e55ed.types import Signal

class FundingRateProducer:
    def __init__(self, config: dict):
        self.api_base = "https://api.binance.com/fapi/v1"
        self.extreme_positive = config.get("extreme_positive", 0.03)  # 3% per 8h
        self.extreme_negative = config.get("extreme_negative", -0.03)
    
    def produce(self, symbol: str) -> Signal:
        """Generate signal based on funding extremes."""
        try:
            funding_rate = self._fetch_funding_rate(symbol)
            funding_annual = funding_rate * 365 * 3  # Annualize (3 periods/day)
            
            if funding_rate > self.extreme_positive:
                return Signal(
                    symbol=symbol,
                    signal="short",  # Longs too crowded
                    conviction=7,
                    rationale=(
                        f"{symbol} extreme positive funding: "
                        f"{funding_annual:.1f}% annual (longs crowded)"
                    ),
                    producer="FundingRate",
                    timestamp=int(datetime.now().timestamp()),
                    metadata={"funding_8h": funding_rate, "funding_annual": funding_annual}
                )
            elif funding_rate < self.extreme_negative:
                return Signal(
                    symbol=symbol,
                    signal="long",  # Shorts too crowded
                    conviction=7,
                    rationale=(
                        f"{symbol} extreme negative funding: "
                        f"{funding_annual:.1f}% annual (shorts paying)"
                    ),
                    producer="FundingRate",
                    timestamp=int(datetime.now().timestamp()),
                    metadata={"funding_8h": funding_rate, "funding_annual": funding_annual}
                )
            else:
                return Signal(
                    symbol=symbol,
                    signal="neutral",
                    conviction=0,
                    rationale=f"{symbol} funding neutral: {funding_annual:.1f}% annual",
                    producer="FundingRate",
                    timestamp=int(datetime.now().timestamp()),
                    metadata={"funding_8h": funding_rate}
                )
        
        except Exception as e:
            return Signal(
                symbol=symbol,
                signal="neutral",
                conviction=0,
                rationale=f"Error: {str(e)}",
                producer="FundingRate",
                timestamp=int(datetime.now().timestamp()),
                metadata={"error": str(e)}
            )
    
    def _fetch_funding_rate(self, symbol: str) -> float:
        """Fetch current funding rate from Binance."""
        url = f"{self.api_base}/premiumIndex?symbol={symbol}USDT"
        response = requests.get(url, timeout=10)
        data = response.json()
        return float(data["lastFundingRate"])
```

---

## Melt-Up Detector (Combined)

Combine basis + funding + ETF flows + OI into single score.

```python
"""Detect melt-up conditions (4-signal confluence)."""
from b1e55ed.types import Signal

class MeltUpDetector:
    def produce(self, symbol: str) -> Signal:
        """Check all 4 melt-up conditions."""
        if symbol != "BTC":
            return self._neutral(symbol)
        
        score = 0
        reasons = []
        
        # 1. Basis optimal (3-6%)
        basis = self._get_basis()
        if 3.0 <= basis <= 6.0:
            score += 1
            reasons.append(f"Basis optimal: {basis:.1f}%")
        
        # 2. Funding healthy (<20% annual)
        funding = self._get_funding_annual()
        if 0 < funding < 20:
            score += 1
            reasons.append(f"Funding healthy: {funding:.1f}%")
        
        # 3. ETF inflows (3+ days)
        etf_streak = self._get_etf_inflow_streak()
        if etf_streak >= 3:
            score += 1
            reasons.append(f"ETF inflows: {etf_streak} days")
        
        # 4. OI rising
        oi_change = self._get_oi_change_pct()
        if oi_change > 0:
            score += 1
            reasons.append(f"OI rising: +{oi_change:.1f}%")
        
        # Signal based on score
        if score == 4:
            return Signal(
                symbol=symbol,
                signal="long",
                conviction=10,
                rationale=f"MELT-UP SETUP COMPLETE (4/4): {', '.join(reasons)}",
                producer="MeltUpDetector",
                timestamp=int(datetime.now().timestamp()),
                metadata={"score": score, "reasons": reasons}
            )
        elif score >= 2:
            return Signal(
                symbol=symbol,
                signal="long",
                conviction=5 + score,
                rationale=f"Melt-up forming ({score}/4): {', '.join(reasons)}",
                producer="MeltUpDetector",
                timestamp=int(datetime.now().timestamp()),
                metadata={"score": score, "reasons": reasons}
            )
        else:
            return self._neutral(symbol)
```

---

## Best Practices

### 1. Context Matters
Basis 8% in 2021 bull = normal. Basis 8% in 2024 = crowded. Adjust thresholds by regime.

### 2. Combine Signals
Single metric (basis alone) is noisy. Use confluence (basis + funding + flows).

### 3. Track Historical Extremes
What basis level preceded past crashes? Update thresholds based on realized outcomes.

### 4. Don't Fight the Basis
When basis spikes, it usually gets worse before it gets better. Exit first, ask questions later.

---

## Validation

**Expected metrics:**
- Crash detection: 80%+ recall (catch most crashes)
- False positive rate: <30% (some false alarms OK)
- Lead time: 6-24 hours before cascade (enough to exit)

**Melt-up detection:**
- Precision: 60%+ (when score = 4/4, pump likely)
- False negatives: Many (misses some pumps, that's fine)
- Timing: Early (sets up days before vertical move)

---

*Last updated: 2026-02-19*
