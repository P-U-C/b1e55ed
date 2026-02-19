# Sample Packs

Pre-built templates and examples for extending b1e55ed with custom producers, strategies, and data sources.

---

## Available Packs

### 1. Social Intelligence (`socials/`)
Templates for tracking social media buzz (TikTok, Twitter, Reddit).

**Use cases:**
- Early meme coin detection
- Narrative trend tracking
- Influencer signal extraction

**Examples:**
- TikTok hashtag scraper (Apify)
- Twitter mention counter (search API)
- Reddit sentiment analyzer (PRAW)

---

### 2. TradFi Signals (`tradfi/`)
Traditional finance plumbing indicators (CME basis, funding rates, ETF flows).

**Use cases:**
- BTC crash detection (basis spike → deleveraging)
- Melt-up detection (basis + funding + ETF inflows)
- Risk-on/risk-off regime shifts

**Examples:**
- CME basis proxy (spot vs quarterly futures)
- Perpetual funding rate monitor
- ETF flow tracker (IBIT, FBTC, etc.)

---

### 3. On-Chain Intelligence (`onchain/`)
Blockchain data analysis (whale tracking, DEX flows, cluster detection).

**Use cases:**
- Whale wallet accumulation signals
- Smart money cluster detection
- DEX liquidity flow monitoring

**Examples:**
- Whale tracker (Allium API)
- Wallet cluster detector (sub-wallet identification)
- DEX trade flow analyzer (Uniswap, Jupiter, etc.)

---

### 4. Producer Templates (`producers/`)
Skeleton code for building custom signal producers.

**Includes:**
- Base producer template (all required methods)
- Example: RSI producer (working implementation)
- Testing template (unit + integration tests)

---

### 5. Strategy Templates (`strategies/`)
Skeleton code for building custom trading strategies.

**Includes:**
- Base strategy template (all required methods)
- Example: Confluence strategy (working implementation)
- Backtest validation template

---

## Quick Start

### 1. Browse Available Packs

```bash
ls samples/socials/     # Social media templates
ls samples/tradfi/      # TradFi signal templates
ls samples/onchain/     # On-chain analysis templates
```

### 2. Copy a Template

```bash
# Copy producer template
cp samples/producers/template.py b1e55ed/producers/my_producer.py

# Copy strategy template
cp samples/strategies/template.py b1e55ed/strategies/my_strategy.py
```

### 3. Customize

Edit the copied file:
- Update logic for your use case
- Configure API keys (in config, not code)
- Write rationale generation
- Set conviction criteria

### 4. Register in Config

Add to `config/b1e55ed.yaml`:

```yaml
brain:
  producers:
    - name: my_producer
      module: b1e55ed.producers.my_producer
      class: MyProducer
      enabled: true
      config:
        # Your config here
```

### 5. Test

```bash
# Unit tests
pytest tests/producers/test_my_producer.py

# Integration test
python -c "from b1e55ed.producers.my_producer import MyProducer; \
           p = MyProducer({}); \
           print(p.produce('BTC'))"
```

### 6. Backtest (for strategies)

```bash
python scripts/backtest_strategy.py --strategy MyStrategy --symbols BTC ETH
```

### 7. Enable

Set `enabled: true` in config and restart brain cycle.

---

## Pack Details

Each pack directory includes:

- **README.md** - Overview, API requirements, usage instructions
- **Templates** - Skeleton code with TODOs
- **Examples** - Working implementations you can copy
- **Config samples** - Example YAML configurations
- **Test templates** - How to write tests for your custom code

---

## Contributing Packs

Have a useful producer/strategy you want to share?

1. Add it to the appropriate `samples/` directory
2. Include README with:
   - What it does
   - API requirements (keys, rate limits, costs)
   - Configuration options
   - Example usage
   - Backtest results (for strategies)
3. Submit PR with `[SAMPLE]` prefix in title

**Quality bar:**
- Works out of the box (after config)
- Documented clearly (no "figure it out yourself")
- Tested (unit tests + examples that run)
- No hardcoded secrets (use config)

---

## Roadmap

**Planned sample packs:**

- **Macro Indicators** - Fed rates, inflation, VIX, DXY
- **Insider Trading** - 13F filings, Form 4 cluster buys
- **Event Equities** - PEAD, earnings surprises
- **Cross-Asset** - Crypto/equity correlation, basis arb
- **Prediction Markets** - Polymarket event signals

---

*Last updated: 2026-02-19*
