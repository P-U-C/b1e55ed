# Architecture Overview

How b1e55ed processes signals and executes trades.

---

## System Design

```
┌─────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                          │
│  (Price APIs, On-Chain, Social, TradFi, Macro)              │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                   SIGNAL PRODUCERS                           │
│  (RSI, Momentum, Social, Whale, Funding, etc.)              │
│  Output: Raw signals with conviction + rationale            │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                    BRAIN ENGINE                              │
│  1. Collect signals from all producers                       │
│  2. PCS Enrichment (price/volume/volatility context)        │
│  3. Strategy evaluation (confluence, momentum, etc.)         │
│  4. Position sizing (conviction-weighted)                    │
│  5. Risk checks (DCG, limits, kill switch)                   │
│  Output: Actionable trades with size + rationale            │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                ORDER MANAGEMENT SYSTEM                       │
│  1. Policy enforcement (limits, leverage, exposure)          │
│  2. Idempotency (prevent duplicate orders)                   │
│  3. Execution (Hyperliquid API)                              │
│  4. Position tracking (entry, stops, targets)                │
│  Output: Filled orders in brain.db                          │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                     KARMA SYSTEM                             │
│  1. Record conviction at signal time                         │
│  2. Evaluate outcome when position closes                    │
│  3. Generate scorecard (hit rates per producer/strategy)     │
│  4. Feed learning loop back to producers                     │
│  Output: Calibrated conviction, improved patterns           │
└─────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Brain Engine (`brain/`)

**Purpose:** Central intelligence - collects signals, enriches with context, evaluates strategies, generates trades.

**Key Files:**
- `orchestrator.py` - Main loop coordinator
- `pcs_enricher.py` - Adds price/volume/volatility context to signals
- `feature_store.py` - Snapshots all signals per cycle (frozen history)
- `synthesizer.py` - Combines signals into actionable insights (future)

**Data Flow:**
```python
def run_cycle(symbols: list[str]) -> dict:
    # 1. Collect signals from all producers
    signals = collect_signals(symbols)
    
    # 2. Enrich with PCS context
    enriched = pcs_enricher.enrich(signals)
    
    # 3. Snapshot to feature store (frozen history)
    feature_store.save_snapshot(enriched)
    
    # 4. Evaluate strategies
    trades = evaluate_strategies(enriched)
    
    # 5. Submit to OMS
    for trade in trades:
        oms.submit_order(trade)
    
    return {"signals": len(signals), "trades": len(trades)}
```

**Extension Points:**
- Add producers via `ExtensionRegistry`
- Add strategies via `StrategyRegistry`
- Custom enrichment via `pcs_enricher` plugins

---

### 2. Signal Producers (`producers/`)

**Purpose:** Independent intelligence sources that generate signals (long/short/neutral) with conviction + rationale.

**Interface:**
```python
class SignalProducer(Protocol):
    def produce(self, symbol: str) -> Signal:
        """Generate a signal for the given symbol."""
        pass
```

**Signal Schema:**
```python
@dataclass
class Signal:
    symbol: str                # Asset ticker (e.g., "BTC")
    signal: Literal["long", "short", "neutral"]
    conviction: int            # 1-10 (10 = highest)
    rationale: str             # Human-readable reasoning
    producer: str              # Producer name (e.g., "RSI")
    timestamp: int             # Unix timestamp
    metadata: dict[str, Any]   # Producer-specific data
```

**Current Producers:**
1. **RSI** - Oversold (<30) / overbought (>70) signals
2. **Momentum** - Price velocity (20-day lookback)
3. **Social** - TikTok/Twitter/Reddit buzz tracking
4. **Whale** - Large wallet accumulation/distribution
5. **Funding** - Perpetual funding rate extremes

**Adding a New Producer:**
See `docs/developers.md` for full guide.

---

### 3. Strategies (`strategies/`)

**Purpose:** Combine multiple signals into trade decisions with position sizing.

**Interface:**
```python
class Strategy(Protocol):
    def evaluate(self, signals: list[Signal]) -> list[Trade]:
        """Evaluate signals and generate trades."""
        pass
```

**Current Strategies:**
1. **ConfluenceStrategy** - Requires 2+ producers agree
2. **MomentumStrategy** - Momentum signal + volume confirmation
3. **MACrossover** - Fast MA crosses slow MA + trend alignment
4. **CombinedStrategy** - Momentum + MA crossover (best backtest results)
5. **RSIOversold** - RSI <30 + price near support (simple)

**Strategy Output:**
```python
@dataclass
class Trade:
    symbol: str
    direction: Literal["long", "short"]
    size: float                # Position size (% of capital)
    entry: float               # Target entry price
    stop: float                # Stop loss
    target: float              # Take profit
    rationale: str             # Why this trade
    strategy: str              # Strategy name
    conviction: int            # Aggregated conviction (1-10)
```

**Adding a New Strategy:**
See `docs/developers.md` for full guide.

---

### 4. Data Layer (`data/`)

**Purpose:** Historical price data, features, and market context.

**Structure:**
```
data/
├── ohlcv/             # Raw OHLCV (5min, 1h, 1d candles)
├── features/          # Derived indicators (RSI, MACD, volume MA)
├── funding/           # Perpetual funding rates
├── fear_greed/        # Market sentiment index
└── metadata/          # Asset info (market cap, liquidity)
```

**Data Sources:**
- **OHLCV:** Binance API (free, 5+ years history)
- **Funding:** Binance perp API
- **On-Chain:** Allium API (requires key)
- **Social:** Apify TikTok scraper (requires key)
- **TradFi:** CME basis proxy via custom script

**Data Collection:**
```bash
# Bulk historical download (run once)
python scripts/collectors/bulk_ohlcv.py --symbols BTC ETH SOL --timeframes 1h 1d

# Incremental updates (run daily)
python scripts/collectors/incremental_ohlcv.py
```

---

### 5. OMS (Order Management System) (`execution/`)

**Purpose:** Policy enforcement, idempotency, execution, position tracking.

**Key Features:**
- **Policy Enforcement:** Max position size (15%), max leverage (3x), sector limits
- **Idempotency:** Prevents duplicate orders via hash-based deduplication
- **Paper Trading:** Simulated execution with realistic fills
- **Live Trading:** Hyperliquid API integration (when ready)
- **Position Tracking:** Entry/exit, P&L, stops hit, targets reached

**Safety Guards:**
1. **DCG (Don't Cross the Guys)** - Blocks trades in restricted symbols
2. **Kill Switch** - Emergency shutdown on unusual activity
3. **Redaction** - Scrubs sensitive data from logs

**Execution Flow:**
```python
# 1. Validate trade against policy
if not policy.validate(trade):
    raise PolicyViolation(...)

# 2. Check idempotency (prevent duplicates)
if oms.is_duplicate(trade):
    return {"status": "duplicate"}

# 3. Submit to exchange
order = exchange.place_order(trade)

# 4. Record in database
oms.record_order(order)

# 5. Update position tracker
positions.update(order)
```

---

### 6. Database (`brain.db`)

**Purpose:** Event-sourced storage for all signals, trades, positions.

**Schema:**
```sql
-- Signal events (producer outputs)
CREATE TABLE signal_events (
    id INTEGER PRIMARY KEY,
    symbol TEXT,
    signal TEXT,                  -- long/short/neutral
    conviction INTEGER,           -- 1-10
    producer TEXT,
    rationale TEXT,
    metadata TEXT,                -- JSON
    timestamp INTEGER,
    hash TEXT UNIQUE              -- SHA256 for deduplication
);

-- Trade events (strategy outputs)
CREATE TABLE trade_events (
    id INTEGER PRIMARY KEY,
    symbol TEXT,
    direction TEXT,               -- long/short
    size REAL,
    entry REAL,
    stop REAL,
    target REAL,
    strategy TEXT,
    rationale TEXT,
    conviction INTEGER,
    timestamp INTEGER,
    hash TEXT UNIQUE
);

-- Order events (execution records)
CREATE TABLE order_events (
    id INTEGER PRIMARY KEY,
    trade_id INTEGER,
    status TEXT,                  -- pending/filled/rejected/cancelled
    filled_price REAL,
    filled_size REAL,
    exchange TEXT,
    exchange_order_id TEXT,
    timestamp INTEGER,
    FOREIGN KEY (trade_id) REFERENCES trade_events(id)
);

-- Position events (tracking)
CREATE TABLE position_events (
    id INTEGER PRIMARY KEY,
    symbol TEXT,
    side TEXT,
    entry_price REAL,
    size REAL,
    stop REAL,
    target REAL,
    status TEXT,                  -- open/closed/stopped
    exit_price REAL,
    pnl REAL,
    opened_at INTEGER,
    closed_at INTEGER
);
```

**Event Sourcing Benefits:**
- Full audit trail (every signal, trade, fill)
- Reproducible (replay events to reconstruct state)
- Hash chain integrity (prevents tampering)
- Easy debugging (query historical events)

---

### 7. API (`api/`)

**Purpose:** REST endpoints for external control and monitoring.

**Endpoints:**
- `GET /health` - System status
- `GET /signals` - Recent signals with filters
- `GET /positions` - Open positions
- `POST /scan` - Trigger manual brain cycle
- `GET /strategies` - Available strategies with stats

**Authentication:**
- Bearer token via `B1E55ED_API__AUTH_TOKEN`
- Rate limiting: 100 req/min per IP
- CORS enabled for dashboard

**Usage:**
```bash
# Trigger manual scan
curl -H "Authorization: Bearer $TOKEN" \
  -X POST http://localhost:5050/scan

# Get recent signals for BTC
curl http://localhost:5050/signals?symbol=BTC&limit=10
```

See `docs/api-reference.md` for full spec.

---

### 8. Dashboard (`dashboard/`)

**Purpose:** Web UI for monitoring signals, positions, performance.

**Features:**
- Multi-asset price monitor (live updates every 5s)
- Recent signals table (filterable by producer, symbol)
- Open positions tracker (entry, P&L, stops, targets)
- Strategy performance scorecard (Sharpe, win rate, max DD)
- Brain cycle status (last run, next run, health)

**Tech Stack:**
- Backend: FastAPI + Jinja2 templates
- Frontend: HTMX (no React/Vue - keep it simple)
- Styling: Tailwind CSS (hybrid PUC/CRT aesthetic)
- Updates: SSE (Server-Sent Events) for live data

**Aesthetic:**
- PUC shell: Warm neutrals, film grain, JetBrains Mono 300
- CRT data zones: Green live numbers, scanlines, terminal density
- No crypto-twitter casual jargon - direct, action-first language

---

## Data Flow Example

**Scenario:** Brain cycle detects BTC long opportunity

```
1. PRODUCERS (8:00:00 AM)
   ├─ RSI Producer: "BTC RSI = 28 (oversold)" → conviction 7
   ├─ Momentum Producer: "BTC +3.2% in 24h (bullish)" → conviction 6
   ├─ Whale Producer: "3 large wallets accumulated 120 BTC" → conviction 8
   └─ Funding Producer: "BTC funding = -0.02% (shorts paying)" → conviction 7

2. BRAIN (8:00:05 AM)
   ├─ Collect 4 signals for BTC
   ├─ PCS Enrich: Add price ($58,234), volume (high), volatility (low)
   ├─ Save snapshot to feature store
   └─ Evaluate strategies

3. STRATEGY: CombinedStrategy (8:00:06 AM)
   ├─ Check confluence: 3/4 producers agree (long) ✓
   ├─ Calculate size: Avg conviction 7 → 5% position
   ├─ Set stop: -3% from entry ($56,487)
   ├─ Set target: +10% from entry ($64,057)
   └─ Output: Trade(symbol="BTC", direction="long", size=0.05, ...)

4. OMS (8:00:07 AM)
   ├─ Validate policy: 5% < 15% max ✓, no leverage ✓
   ├─ Check idempotency: Hash not seen before ✓
   ├─ Execute: Hyperliquid API (or paper trade)
   ├─ Record: trade_events, order_events, position_events
   └─ Output: Position HL-123 opened

5. KARMA (later, when position closes)
   ├─ Record conviction: 7 at signal time
   ├─ Evaluate outcome: +8.2% profit (win)
   ├─ Update scorecard: CombinedStrategy win rate 62% → 63%
   └─ Feed learning: "High RSI + whale accumulation = strong signal"
```

---

## Extension Points

### Adding a Signal Producer

1. Create `producers/my_producer.py`:
```python
from b1e55ed.types import Signal
import time

class MyProducer:
    def produce(self, symbol: str) -> Signal:
        # Your logic here
        conviction = calculate_conviction(symbol)
        
        return Signal(
            symbol=symbol,
            signal="long" if conviction > 6 else "neutral",
            conviction=conviction,
            rationale="Custom indicator triggered",
            producer="MyProducer",
            timestamp=int(time.time()),
            metadata={"custom_field": 123}
        )
```

2. Register in `config/b1e55ed.yaml`:
```yaml
brain:
  producers:
    - name: my_producer
      module: b1e55ed.producers.my_producer
      class: MyProducer
      enabled: true
```

3. Add tests in `tests/producers/test_my_producer.py`

See `docs/developers.md` for full guide.

---

### Adding a Data Source

1. Create collector script in `scripts/collectors/my_source.py`
2. Save data to `data/my_source/` in standardized format (CSV or Parquet)
3. Update `data/collectors/README.md` with source info
4. Add to cron if recurring updates needed

**Example:**
```python
# scripts/collectors/fear_greed.py
import requests
import pandas as pd
from pathlib import Path

def collect_fear_greed():
    url = "https://api.alternative.me/fng/?limit=365"
    response = requests.get(url)
    data = response.json()["data"]
    
    df = pd.DataFrame(data)
    df.to_parquet("data/fear_greed/history.parquet")
    
if __name__ == "__main__":
    collect_fear_greed()
```

---

### Adding a Strategy

1. Create `strategies/my_strategy.py`:
```python
from b1e55ed.types import Signal, Trade

class MyStrategy:
    def evaluate(self, signals: list[Signal]) -> list[Trade]:
        trades = []
        
        for signal in signals:
            if self.should_trade(signal):
                trades.append(Trade(
                    symbol=signal.symbol,
                    direction=signal.signal,
                    size=self.calculate_size(signal.conviction),
                    entry=get_current_price(signal.symbol),
                    stop=self.calculate_stop(signal),
                    target=self.calculate_target(signal),
                    rationale=f"MyStrategy: {signal.rationale}",
                    strategy="MyStrategy",
                    conviction=signal.conviction
                ))
        
        return trades
```

2. Register in config
3. Add tests
4. Run backtest validation

See `docs/developers.md` for full guide.

---

## Monitoring & Observability

### Logs

**Structure:**
```
logs/
├── brain.log          # Brain cycle activity
├── api.log            # API requests
├── dashboard.log      # Dashboard access
├── oms.log            # Order execution
└── errors.log         # All errors (aggregated)
```

**Log Format:**
```
[2026-02-19 08:00:00] [INFO] [brain.orchestrator] Cycle started for 5 symbols
[2026-02-19 08:00:05] [INFO] [brain.pcs_enricher] Enriched 12 signals
[2026-02-19 08:00:07] [INFO] [execution.oms] Order submitted: HL-123 BTC LONG 0.05
[2026-02-19 08:00:10] [ERROR] [producers.social] TikTok API rate limit hit
```

### Health Checks

```bash
# System health
curl http://localhost:5050/health

# Response
{
  "status": "healthy",
  "components": {
    "database": "ok",
    "api": "ok",
    "producers": {"rsi": "ok", "social": "degraded"},
    "last_cycle": "2026-02-19T08:00:00Z"
  }
}
```

### Alerts

**Trigger conditions:**
- Position hits stop loss
- Position reaches target
- Producer fails 3 times in a row
- Database write error
- Kill switch activated

**Delivery:**
- Telegram notification (via OpenClaw)
- Email (via SMTP)
- Log to `logs/alerts.log`

---

## Security

### Secret Management

**Never hardcode:**
- API keys (Allium, Nansen, Hyperliquid)
- Auth tokens (API, dashboard)
- Master password (database encryption)

**Storage:**
- Environment variables (`.env` file, gitignored)
- System keyring (for production)
- OpenClaw secrets (encrypted at rest)

**Validation:**
```bash
# CI check for hardcoded secrets
grep -E "(sk-[a-zA-Z0-9]{20,}|xai-[a-zA-Z0-9]{20,})" -r b1e55ed/
```

### Access Control

**API:**
- Bearer token required for `/scan`, `/positions`
- Rate limiting: 100 req/min
- IP whitelist (optional)

**Dashboard:**
- Optional auth token
- Read-only by default
- HTTPS in production (nginx proxy)

---

## Performance

### Optimization Targets

- Brain cycle: <10s for 50 assets
- API response: <200ms (95th percentile)
- Dashboard load: <1s initial, <100ms updates
- Database writes: <50ms per event

### Bottlenecks

1. **PCS Enrichment** - API calls to price feeds (cache 5s)
2. **Backtest Sweeps** - 96K combos = hours (parallelize)
3. **Social Scraping** - TikTok rate limits (queue + retry)

---

*Last updated: 2026-02-19*
