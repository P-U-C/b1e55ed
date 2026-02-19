# Developer Guide

How to extend b1e55ed with custom producers, strategies, and data sources.

---

## Adding a Signal Producer

Producers generate trading signals for assets. They run independently and output conviction-scored signals.

### 1. Create Producer File

**Location:** `b1e55ed/producers/your_producer.py`

**Template:**
```python
"""Your Producer - Brief description."""
from dataclasses import dataclass
import time
from b1e55ed.types import Signal

@dataclass
class YourProducerConfig:
    """Configuration for your producer."""
    threshold: float = 0.7
    lookback_days: int = 30
    enabled: bool = True

class YourProducer:
    """
    Generates signals based on [your logic].
    
    Signal Logic:
    - Long: [condition]
    - Short: [condition]
    - Neutral: [default]
    
    Conviction (1-10):
    - 8-10: Strong signal with [criteria]
    - 5-7: Moderate signal with [criteria]
    - 1-4: Weak signal with [criteria]
    """
    
    def __init__(self, config: YourProducerConfig):
        self.config = config
        self.name = "YourProducer"
    
    def produce(self, symbol: str) -> Signal:
        """Generate signal for the given symbol."""
        try:
            # 1. Fetch your data
            data = self._fetch_data(symbol)
            
            # 2. Calculate your indicator
            indicator_value = self._calculate_indicator(data)
            
            # 3. Determine signal direction
            signal_direction = self._determine_direction(indicator_value)
            
            # 4. Calculate conviction (1-10)
            conviction = self._calculate_conviction(indicator_value)
            
            # 5. Generate rationale
            rationale = self._generate_rationale(
                symbol, indicator_value, signal_direction
            )
            
            return Signal(
                symbol=symbol,
                signal=signal_direction,
                conviction=conviction,
                rationale=rationale,
                producer=self.name,
                timestamp=int(time.time()),
                metadata={
                    "indicator_value": indicator_value,
                    "threshold": self.config.threshold,
                    # Add any other useful debugging info
                }
            )
        
        except Exception as e:
            # Fallback to neutral on errors
            return Signal(
                symbol=symbol,
                signal="neutral",
                conviction=0,
                rationale=f"Error: {str(e)}",
                producer=self.name,
                timestamp=int(time.time()),
                metadata={"error": str(e)}
            )
    
    def _fetch_data(self, symbol: str) -> dict:
        """Fetch required data for analysis."""
        # Implement your data fetching logic
        # Examples:
        # - Read from data/ directory
        # - Call external API
        # - Query database
        raise NotImplementedError
    
    def _calculate_indicator(self, data: dict) -> float:
        """Calculate your custom indicator."""
        # Implement your indicator logic
        raise NotImplementedError
    
    def _determine_direction(self, value: float) -> str:
        """Map indicator value to signal direction."""
        if value > self.config.threshold:
            return "long"
        elif value < -self.config.threshold:
            return "short"
        else:
            return "neutral"
    
    def _calculate_conviction(self, value: float) -> int:
        """Map indicator strength to conviction (1-10)."""
        # Example: Linear mapping from threshold to max
        strength = abs(value)
        if strength < self.config.threshold:
            return 0  # Neutral
        
        # Map [threshold, 1.0] to [5, 10]
        conviction = int(5 + (strength - self.config.threshold) * 10)
        return min(max(conviction, 1), 10)
    
    def _generate_rationale(
        self, symbol: str, value: float, direction: str
    ) -> str:
        """Generate human-readable rationale."""
        return (
            f"{symbol} {self.name} indicator = {value:.2f} "
            f"({'above' if value > 0 else 'below'} threshold {self.config.threshold})"
        )
```

### 2. Register Producer

**Config:** `config/b1e55ed.yaml`

```yaml
brain:
  producers:
    - name: your_producer
      module: b1e55ed.producers.your_producer
      class: YourProducer
      enabled: true
      config:
        threshold: 0.7
        lookback_days: 30
```

**Extension Registry:** `b1e55ed/brain/extensions.py`

```python
def load_producers(config: dict) -> list[Any]:
    """Load all enabled producers from config."""
    producers = []
    
    for producer_config in config.get("brain", {}).get("producers", []):
        if not producer_config.get("enabled", True):
            continue
        
        # Import the module
        module_path = producer_config["module"]
        class_name = producer_config["class"]
        module = importlib.import_module(module_path)
        producer_class = getattr(module, class_name)
        
        # Instantiate with config
        producer = producer_class(producer_config.get("config", {}))
        producers.append(producer)
    
    return producers
```

### 3. Write Tests

**Location:** `tests/producers/test_your_producer.py`

```python
"""Tests for YourProducer."""
import pytest
from b1e55ed.producers.your_producer import YourProducer, YourProducerConfig

def test_produce_long_signal():
    """Test long signal generation."""
    config = YourProducerConfig(threshold=0.7)
    producer = YourProducer(config)
    
    signal = producer.produce("BTC")
    
    assert signal.symbol == "BTC"
    assert signal.signal in ["long", "short", "neutral"]
    assert 0 <= signal.conviction <= 10
    assert len(signal.rationale) > 0
    assert signal.producer == "YourProducer"

def test_conviction_scaling():
    """Test conviction scales with indicator strength."""
    config = YourProducerConfig(threshold=0.5)
    producer = YourProducer(config)
    
    # Mock indicator values
    weak_signal = producer._calculate_conviction(0.6)   # Just above threshold
    strong_signal = producer._calculate_conviction(0.9) # Well above threshold
    
    assert weak_signal < strong_signal
    assert 1 <= weak_signal <= 10
    assert 1 <= strong_signal <= 10

def test_error_handling():
    """Test graceful error handling."""
    config = YourProducerConfig()
    producer = YourProducer(config)
    
    # Force an error (bad symbol, API down, etc.)
    signal = producer.produce("INVALID_SYMBOL")
    
    assert signal.signal == "neutral"
    assert signal.conviction == 0
    assert "Error" in signal.rationale
```

**Run tests:**
```bash
pytest tests/producers/test_your_producer.py -v
```

### 4. Example: Social Sentiment Producer

**Real implementation from b1e55ed:**

```python
"""Social sentiment producer - TikTok/Twitter buzz."""
import requests
from collections import Counter
from b1e55ed.types import Signal

class SocialProducer:
    """Tracks social media mentions and sentiment."""
    
    def __init__(self, config: dict):
        self.apify_token = config.get("apify_token")
        self.threshold = config.get("mention_threshold", 50)
    
    def produce(self, symbol: str) -> Signal:
        """Generate signal based on social buzz."""
        # Fetch TikTok mentions
        mentions = self._fetch_tiktok_mentions(symbol)
        
        if mentions >= self.threshold:
            conviction = min(int(mentions / 10), 10)
            return Signal(
                symbol=symbol,
                signal="long",  # Buzz usually precedes pumps
                conviction=conviction,
                rationale=f"{symbol} trending on TikTok: {mentions} mentions",
                producer="Social",
                timestamp=int(time.time()),
                metadata={"mentions": mentions, "source": "tiktok"}
            )
        else:
            return Signal(
                symbol=symbol,
                signal="neutral",
                conviction=0,
                rationale=f"{symbol} low social activity: {mentions} mentions",
                producer="Social",
                timestamp=int(time.time()),
                metadata={"mentions": mentions}
            )
    
    def _fetch_tiktok_mentions(self, symbol: str) -> int:
        """Fetch TikTok mentions via Apify."""
        url = "https://api.apify.com/v2/acts/clockworks~free-tiktok-scraper/runs"
        payload = {
            "searchQueries": [f"#{symbol.lower()} crypto"],
            "resultsPerPage": 40
        }
        headers = {"Authorization": f"Bearer {self.apify_token}"}
        
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        
        return len(data.get("items", []))
```

---

## Adding a Strategy

Strategies combine multiple signals into trade decisions with position sizing.

### 1. Create Strategy File

**Location:** `b1e55ed/strategies/your_strategy.py`

```python
"""Your Strategy - Brief description."""
from dataclasses import dataclass
from b1e55ed.types import Signal, Trade

@dataclass
class YourStrategyConfig:
    """Configuration for your strategy."""
    min_conviction: int = 7
    min_signals: int = 2
    position_size_base: float = 0.03  # 3% per position

class YourStrategy:
    """
    Strategy Logic:
    - [Describe entry conditions]
    - [Describe exit conditions]
    - [Describe position sizing rules]
    
    Backtest Results:
    - Sharpe: [value]
    - Win Rate: [value]
    - Max DD: [value]
    """
    
    def __init__(self, config: YourStrategyConfig):
        self.config = config
        self.name = "YourStrategy"
    
    def evaluate(self, signals: list[Signal]) -> list[Trade]:
        """Evaluate signals and generate trades."""
        trades = []
        
        # Group signals by symbol
        by_symbol = self._group_by_symbol(signals)
        
        for symbol, symbol_signals in by_symbol.items():
            trade = self._evaluate_symbol(symbol, symbol_signals)
            if trade:
                trades.append(trade)
        
        return trades
    
    def _evaluate_symbol(
        self, symbol: str, signals: list[Signal]
    ) -> Trade | None:
        """Evaluate signals for a single symbol."""
        # Filter to high-conviction signals
        strong_signals = [
            s for s in signals 
            if s.conviction >= self.config.min_conviction
        ]
        
        if len(strong_signals) < self.config.min_signals:
            return None  # Not enough conviction
        
        # Determine consensus direction
        long_count = sum(1 for s in strong_signals if s.signal == "long")
        short_count = sum(1 for s in strong_signals if s.signal == "short")
        
        if long_count > short_count:
            direction = "long"
        elif short_count > long_count:
            direction = "short"
        else:
            return None  # No consensus
        
        # Calculate position size (conviction-weighted)
        avg_conviction = sum(s.conviction for s in strong_signals) / len(strong_signals)
        position_size = self._calculate_position_size(avg_conviction)
        
        # Get current price and set stops/targets
        entry_price = self._get_current_price(symbol)
        stop_loss = self._calculate_stop(entry_price, direction)
        take_profit = self._calculate_target(entry_price, direction)
        
        # Generate rationale
        rationale = self._generate_rationale(symbol, strong_signals, direction)
        
        return Trade(
            symbol=symbol,
            direction=direction,
            size=position_size,
            entry=entry_price,
            stop=stop_loss,
            target=take_profit,
            rationale=rationale,
            strategy=self.name,
            conviction=int(avg_conviction)
        )
    
    def _calculate_position_size(self, conviction: int) -> float:
        """Scale position size by conviction."""
        # 3% base at conviction 7, up to 6% at conviction 10
        return self.config.position_size_base * (conviction / 7)
    
    def _calculate_stop(self, entry: float, direction: str) -> float:
        """Set stop loss at 3% from entry."""
        if direction == "long":
            return entry * 0.97  # 3% below entry
        else:
            return entry * 1.03  # 3% above entry
    
    def _calculate_target(self, entry: float, direction: str) -> float:
        """Set take profit at 10% from entry."""
        if direction == "long":
            return entry * 1.10  # 10% above entry
        else:
            return entry * 0.90  # 10% below entry
    
    def _generate_rationale(
        self, symbol: str, signals: list[Signal], direction: str
    ) -> str:
        """Combine signal rationales."""
        producers = [s.producer for s in signals]
        return (
            f"{self.name}: {direction.upper()} {symbol} - "
            f"{len(signals)} signals agree ({', '.join(producers)})"
        )
    
    def _group_by_symbol(
        self, signals: list[Signal]
    ) -> dict[str, list[Signal]]:
        """Group signals by symbol."""
        grouped = {}
        for signal in signals:
            if signal.symbol not in grouped:
                grouped[signal.symbol] = []
            grouped[signal.symbol].append(signal)
        return grouped
    
    def _get_current_price(self, symbol: str) -> float:
        """Fetch current price (implement via data layer)."""
        raise NotImplementedError
```

### 2. Register Strategy

**Config:** `config/b1e55ed.yaml`

```yaml
brain:
  strategies:
    - name: your_strategy
      module: b1e55ed.strategies.your_strategy
      class: YourStrategy
      enabled: true
      config:
        min_conviction: 7
        min_signals: 2
        position_size_base: 0.03
```

### 3. Backtest Validation

**Required before production:**

```python
# scripts/backtest_strategy.py
from b1e55ed.backtest import BacktestEngine
from b1e55ed.strategies.your_strategy import YourStrategy

def backtest_your_strategy():
    """Backtest with historical data."""
    engine = BacktestEngine(
        start_date="2020-01-01",
        end_date="2025-12-31",
        initial_capital=10000,
        symbols=["BTC", "ETH", "SOL"]
    )
    
    strategy = YourStrategy(config={})
    results = engine.run(strategy)
    
    print(f"Sharpe Ratio: {results['sharpe']:.2f}")
    print(f"Win Rate: {results['win_rate']:.1f}%")
    print(f"Max Drawdown: {results['max_drawdown']:.1f}%")
    
    return results

if __name__ == "__main__":
    backtest_your_strategy()
```

**Validation gates:**
- Sharpe > 0.5
- Win Rate > 55% (for high-conviction signals)
- Max Drawdown < 30%

---

## Adding a Data Source

Data sources feed producers with market context (price, volume, on-chain, social, macro).

### 1. Create Collector Script

**Location:** `scripts/collectors/your_source.py`

```python
"""Collector for [Your Data Source]."""
import pandas as pd
from pathlib import Path
import requests

def collect_your_data(symbols: list[str], output_dir: str = "data/your_source"):
    """
    Collect data from [source] and save to standardized format.
    
    Args:
        symbols: List of symbols to collect (e.g., ["BTC", "ETH"])
        output_dir: Where to save the data
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    for symbol in symbols:
        print(f"Collecting {symbol}...")
        
        # 1. Fetch data from API
        data = fetch_api_data(symbol)
        
        # 2. Transform to standard format
        df = transform_data(data)
        
        # 3. Save to parquet (efficient, typed storage)
        output_file = output_path / f"{symbol}.parquet"
        df.to_parquet(output_file)
        
        print(f"  Saved {len(df)} rows to {output_file}")

def fetch_api_data(symbol: str) -> dict:
    """Fetch from external API."""
    url = f"https://api.example.com/data/{symbol}"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def transform_data(raw_data: dict) -> pd.DataFrame:
    """Transform API response to standard schema."""
    df = pd.DataFrame(raw_data["items"])
    
    # Standardize columns
    df = df.rename(columns={
        "timestamp_ms": "timestamp",
        "value": "indicator_value"
    })
    
    # Convert timestamps to datetime
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    
    # Sort by time
    df = df.sort_values("timestamp")
    
    return df

if __name__ == "__main__":
    import sys
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["BTC", "ETH"]
    collect_your_data(symbols)
```

### 2. Document the Source

**Location:** `data/collectors/README.md`

```markdown
## Your Data Source

**API:** https://api.example.com
**Rate Limit:** 100 requests/hour
**Cost:** Free tier (1000 calls/month)
**Auth:** API key required (env: `YOUR_SOURCE_API_KEY`)

**Data Schema:**
- `timestamp` - Unix milliseconds
- `symbol` - Asset ticker
- `indicator_value` - Your metric (float)

**Collection:**
```bash
# One-time historical
python scripts/collectors/your_source.py BTC ETH SOL

# Daily incremental (add to cron)
python scripts/collectors/your_source.py BTC ETH
```

**Storage:** `data/your_source/{symbol}.parquet`
```

### 3. Add to Cron (if recurring)

**Location:** Add to OpenClaw cron or systemd timer

```yaml
# ~/.openclaw/gateway.yaml (if using OpenClaw cron)
cron:
  jobs:
    - name: your-source-collector
      schedule:
        kind: cron
        expr: "0 6 * * *"  # Daily at 6 AM
        tz: "UTC"
      payload:
        kind: systemEvent
        text: "python3 /path/to/b1e55ed/scripts/collectors/your_source.py BTC ETH SOL"
      sessionTarget: isolated
```

### 4. Example: Fear & Greed Index

**Real implementation:**

```python
"""Collect Crypto Fear & Greed Index."""
import requests
import pandas as pd
from pathlib import Path

def collect_fear_greed(days: int = 365):
    """Fetch historical fear & greed data."""
    url = f"https://api.alternative.me/fng/?limit={days}"
    response = requests.get(url)
    data = response.json()["data"]
    
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
    df["value"] = df["value"].astype(int)
    
    output_path = Path("data/fear_greed/history.parquet")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path)
    
    print(f"Saved {len(df)} days of F&G data")

if __name__ == "__main__":
    collect_fear_greed()
```

---

## Testing Guidelines

### Unit Tests (Fast, Isolated)

**What to test:**
- Producer signal generation logic
- Strategy evaluation logic
- Data transformations
- Conviction calculations

**Example:**
```python
def test_momentum_producer():
    """Test momentum calculation."""
    producer = MomentumProducer(lookback=20)
    
    # Mock price data
    mock_data = {"prices": [100, 105, 110, 115, 120]}
    
    signal = producer._calculate_signal(mock_data)
    assert signal == "long"  # Upward momentum
```

### Integration Tests (Slower, End-to-End)

**What to test:**
- Full brain cycle (producers → strategies → trades)
- Database writes (signals, trades, positions)
- API endpoints (scan, signals, positions)

**Example:**
```python
def test_brain_cycle_integration():
    """Test full brain cycle."""
    config = load_test_config()
    orchestrator = BrainOrchestrator(config)
    
    results = orchestrator.run_cycle(symbols=["BTC"])
    
    assert results["signals"] > 0
    assert results["trades"] >= 0
    
    # Check database
    db = Database(":memory:")
    signals = db.query("SELECT * FROM signal_events")
    assert len(signals) == results["signals"]
```

### Backtest Validation (Slowest, Historical)

**What to test:**
- Strategy performance over 2+ years
- Multiple market regimes (bull, bear, sideways)
- Walk-forward validation (prevent overfitting)

**Example:**
```bash
# Run 96K parameter sweep
python scripts/backtest_sweep.py \
  --strategy YourStrategy \
  --symbols BTC ETH SOL \
  --start 2020-01-01 \
  --end 2025-12-31 \
  --output results/your_strategy_sweep.csv
```

---

## Sample Packs

Pre-built templates for common use cases. See `samples/` directory.

### Structure

```
samples/
├── socials/               # Social media intelligence
│   ├── tiktok_scraper.py
│   ├── twitter_scraper.py
│   ├── reddit_scraper.py
│   └── README.md
├── tradfi/                # Traditional finance signals
│   ├── cme_basis.py
│   ├── funding_rates.py
│   ├── etf_flows.py
│   └── README.md
├── onchain/               # On-chain intelligence
│   ├── whale_tracker.py
│   ├── cluster_detector.py
│   ├── dex_flows.py
│   └── README.md
├── producers/             # Producer templates
│   └── template.py
└── strategies/            # Strategy templates
    └── template.py
```

### Usage

1. **Browse samples:** `ls samples/socials/`
2. **Copy template:** `cp samples/producers/template.py b1e55ed/producers/my_producer.py`
3. **Customize:** Edit config, logic, rationale
4. **Register:** Add to `config/b1e55ed.yaml`
5. **Test:** Run unit tests + backtest
6. **Enable:** Set `enabled: true` in config

---

## Best Practices

### Producer Design

1. **Fail gracefully** - Return neutral signal on errors (don't crash brain cycle)
2. **Cache aggressively** - Avoid redundant API calls (5s TTL for price data)
3. **Document conviction** - Explain what makes a signal 10 vs 5 vs 1
4. **Include metadata** - Store raw values for debugging/analysis
5. **Test edge cases** - Missing data, API down, invalid symbols

### Strategy Design

1. **Require confluence** - Single signals are often noise (2+ producers)
2. **Scale conviction** - Higher conviction → larger position size
3. **Set explicit stops** - Never enter without stop loss
4. **Backtest rigorously** - 2+ years, multiple regimes, walk-forward validation
5. **Document assumptions** - What market conditions does this work in?

### Data Collection

1. **Standardize schema** - timestamp, symbol, value (consistent across sources)
2. **Use parquet** - Faster than CSV, typed, compressed
3. **Version data** - Track when collected, what version of script
4. **Handle gaps** - Missing days, API downtime, rate limits
5. **Monitor costs** - API usage, storage, processing time

### Testing

1. **Unit test pure logic** - Fast, isolated, run on every commit
2. **Integration test flows** - Slower, run before PR merge
3. **Backtest before prod** - Validate on historical data first
4. **Paper trade first** - 30 days minimum before live capital
5. **Monitor in production** - Alert on unexpected behavior

---

## Common Pitfalls

### Overfitting
**Problem:** Strategy works great on historical data, fails in production.
**Solution:** Walk-forward validation, FDR correction, out-of-sample testing.

### Look-Ahead Bias
**Problem:** Using future data to make past decisions (backtest cheating).
**Solution:** Strict timestamp ordering, only use data available at signal time.

### Survivorship Bias
**Problem:** Testing only on assets that still exist today.
**Solution:** Include delisted assets, account for rug pulls.

### Parameter Tuning
**Problem:** Tweaking parameters until backtest looks good.
**Solution:** Define parameters before testing, penalize complexity.

### Ignoring Costs
**Problem:** Backtest ignores fees, slippage, spread.
**Solution:** Realistic cost model (0.05% taker fee + 0.1% slippage).

---

## Getting Help

- **Docs:** `docs/` (architecture, API reference, deployment)
- **Examples:** `samples/` (templates and sample packs)
- **Tests:** `tests/` (see how existing components work)
- **Issues:** GitHub Issues for bugs/feature requests
- **Discord:** Community support (link in README)

---

*Last updated: 2026-02-19*
