# Producer Configuration Guide

This guide gets you to a working b1e55ed signal setup in ~20 minutes.

> **Terminology note (important):** in the current b1e55ed architecture, **weights are applied at the *domain* level** (curator/onchain/tradfi/social/technical/events), not per-producer. Multiple producers can feed the same domain via different event types. You “enable” most producers by **providing their data endpoints** (env vars); if an endpoint is missing, that producer will run but typically emit no events and show **DEGRADED** health.

---

## 1) What are producers?

**Producers** are signal generators that feed the brain’s synthesis engine.

- Each producer periodically **collects data**, **normalizes** it into a typed signal payload, and **publishes events** into the local DB.
- Those events are mapped into one of **six domains** and converted into feature vectors.
- The synthesis engine combines domain features using **domain weights** → produces a weighted score → the conviction engine turns that into a **PCS** (position conviction score) and decisions.

Why it matters:

- Bad or stale producer inputs degrade a domain and drag overall performance.
- Good, independent producers compound: domains corroborate each other and raise conviction.

---

## 2) The 13 producers

### Default domain weights (system defaults)

Defined in `engine/core/config.py` (`DomainWeights`). Defaults:

| Domain | Default weight |
|---|---:|
| curator | 0.25 |
| onchain | 0.25 |
| tradfi | 0.20 |
| social | 0.15 |
| technical | 0.10 |
| events | 0.05 |

### Producers table

> **Default weight (below)** = the producer’s **domain weight** by default (since weights are domain-level today).

| Producer (config id) | Category (domain) | What it signals | Cost (API/compute) | Default weight | When to enable |
|---|---|---|---|---:|---|
| `curator-intel` | curator | Operator/curator directional view + conviction + rationale | Low (HTTP GET or local JSON file) | 0.25 | When you have discretionary/curated views you trust |
| `ai-consensus` | curator | LLM/ensemble consensus score (-10..+10) + dispersion | Medium–High (LLM/inference endpoint) | 0.25 | When you want “committee of models” / meta-opinion |
| `onchain-flows` | onchain | Whale netflow, exchange flows, active addresses change, 24h momentum | Medium (onchain API/compute) | 0.25 | When flow regimes matter (accumulation/distribution) |
| `stablecoin-supply` | onchain | Stablecoin supply deltas (24h/7d) + mint/burn count | Medium (data endpoint) | 0.25 | When liquidity cycle is a key driver |
| `whale-tracking` | onchain | Smart money netflow + top holders change | Medium (smart money/onchain provider) | 0.25 | When whales/holders lead price (alts especially) |
| `tradfi-basis` | tradfi | Basis, funding proxy, OI change, meltup score | Low–Medium (endpoint) | 0.20 | When BTC/ETH are CME/ETF-driven / basis regimes |
| `etf-flows` | tradfi | Daily ETF flows, streak, cumulative 7d | Medium (endpoint) | 0.20 | When spot ETF flows dominate (BTC/ETH) |
| `social-intel` | social | Social score + direction + contrarian/echo-chamber flags | Medium (social pipeline) | 0.15 | When narratives/CT drive short-term moves |
| `market-sentiment` | social | Fear/greed + 7d change (+ optional CT sentiment) | Low–Medium (endpoint) | 0.15 | When broad risk appetite is the main factor |
| `technical-analysis` | technical | RSI/EMAs/BB position/volume ratio/trend strength/S/R distance | Low–Medium (endpoint) | 0.10 | When structure is clean; trend & mean-reversion regimes |
| `orderbook-depth` | technical | Bid/ask depth, imbalance, liquidity-on-depth score | Medium (endpoint; frequent) | 0.10 | When microstructure/liquidity matters (breakouts, dumps) |
| `price-alerts` | technical | Price/bid/ask/venue (polling “ws-like” feed) | Medium (endpoint; **every 1 min**) | 0.10 | When you need fast price state for technical context |
| `market-events` | events | Catalyst list + headline sentiment + impact score + count | Medium (endpoint; NLP/news) | 0.05 | When catalysts/news drive discontinuities |

## MCP signal access

Every producer auto-registers with the MCP registry on startup.

| Producer | Domain | `mcp_source_url` | Description |
|---|---|---|---|
| TechnicalAnalysis (`technical-analysis`) | technical | `null` | Technical indicators and structure signals for configured symbols. |
| Onchain (`onchain-flows`) | onchain | `null` | On-chain flow and activity metrics. |
| TradFiBasis (`tradfi-basis`) | tradfi | `null` | Basis/funding/open-interest carry regime signals. |
| Sentiment (`market-sentiment`) | social | `null` | Market sentiment and fear/greed risk appetite. |
| Social (`social-intel`) | social | `null` | Narrative/attention-driven social intelligence pipeline. |
| Whale (`whale-tracking`) | onchain | `null` | Whale and smart-money positioning changes. |
| Stablecoin (`stablecoin-supply`) | onchain | `null` | Stablecoin expansion/contraction liquidity proxy. |
| ETF (`etf-flows`) | tradfi | `null` | Spot ETF flow pressure and streak dynamics. |
| Orderbook (`orderbook-depth`) | technical | `null` | Orderbook imbalance and liquidity-depth conditions. |
| Events (`market-events`) | events | `null` | Event/catalyst sentiment and impact scoring. |
| Curator (`curator-intel`) | curator | `null` | Operator/curator directional thesis ingestion. |
| ACI (`ai-consensus`) | curator | `null` | AI consensus directional score from model output. |
| FinancialDatasets (`financial_datasets`) | tradfi | `https://github.com/financial-datasets/mcp-server` | MCP-enabled earnings surprise and fundamentals stream (registered when API key is configured). |

- `mcp_source_url: null` = producer uses REST/WebSocket-style data collection.
- `mcp_source_url: <url>` = producer has an upstream MCP server (for now: `financial_datasets`).

See [mcp.md](mcp.md) for the full operator guide.

---

### Producer details (what it uses, catches/misses, tuning knobs)

Below, **“tuning knobs”** means practical things you can control today: symbols (universe), domain weights, and environment variables for endpoints.

#### `curator-intel` (domain: curator)

- **Data:** HTTP endpoint (`B1E55ED_CURATOR_URL` / `CURATOR_URL`) *or* local JSON file (`B1E55ED_CURATOR_FILE` / `CURATOR_FILE`).
- **Signals it catches:** discretionary theses, structured conviction, “I know something” situations (research, positioning insight).
- **What it misses:** anything you don’t explicitly write down; may be stale if not updated.
- **Tuning knobs:**
  - Provide a simple list payload of `{symbol, direction, conviction, rationale, source}`.
  - Adjust `weights.curator` up when your discretionary edge is strong.

#### `ai-consensus` (domain: curator)

- **Data:** HTTP inference endpoint (`B1E55ED_ACI_URL` / `ACI_URL`).
- **Signals it catches:** meta-opinion/consensus across LLMs or models; useful in narrative confusion.
- **What it misses:** real positioning/flows; can be overconfident in novel regimes.
- **Tuning knobs:**
  - Upstream response parsing is forgiving: it extracts the **last integer** and clamps to **[-10, 10]**.
  - Increase `weights.curator` when you trust your model ensemble; decrease when models lag.

#### `onchain-flows` (domain: onchain)

- **Data:** HTTP endpoint (`B1E55ED_ONCHAIN_FLOWS_URL` / `ONCHAIN_FLOWS_URL`).
- **Signals it catches:** accumulation/distribution via flows; address activity shifts; momentum that’s “real” on-chain.
- **What it misses:** off-chain positioning (perps), TradFi catalysts, social reflexivity.
- **Tuning knobs:** increase `weights.onchain` in accumulation/distribution phases; reduce when price is primarily macro/ETF-driven.

#### `stablecoin-supply` (domain: onchain)

- **Data:** HTTP endpoint (`B1E55ED_STABLECOIN_SUPPLY_URL` / `STABLECOIN_SUPPLY_URL`).
- **Signals it catches:** liquidity expansion/contraction proxies (mint/burn cycles).
- **What it misses:** which assets receive the liquidity; timing can be slow.
- **Tuning knobs:** when liquidity regime is dominant, increase `weights.onchain` (this producer feeds the onchain domain).

#### `whale-tracking` (domain: onchain)

- **Data:** HTTP endpoint (`B1E55ED_WHALE_TRACKING_URL` / `WHALE_TRACKING_URL`).
- **Signals it catches:** smart money netflow; holder concentration changes.
- **What it misses:** retail-driven pumps, macro shocks.
- **Tuning knobs:** increase `weights.onchain` in high-beta alt regimes where whales lead.

#### `tradfi-basis` (domain: tradfi)

- **Data:** HTTP endpoint (`B1E55ED_TRADFI_BASIS_URL` / `TRADFI_BASIS_URL`).
- **Signals it catches:** carry trades, crowded basis, OI expansions, meltup conditions.
- **What it misses:** token-specific onchain/social catalysts.
- **Tuning knobs:** increase `weights.tradfi` in BTC/ETH regimes dominated by CME, funding, basis.

#### `etf-flows` (domain: tradfi)

- **Data:** HTTP endpoint (`B1E55ED_ETF_FLOWS_URL` / `ETF_FLOWS_URL`).
- **Signals it catches:** spot ETF flow-driven pressure (risk-on/off for BTC/ETH).
- **What it misses:** crypto-native flows (onchain), funding/basis microstructure.
- **Tuning knobs:** if you trade BTC/ETH primarily, raise `weights.tradfi`; if you trade alts, lower it.

#### `social-intel` (domain: social)

- **Data:** runs `engine.social.pipeline.run(ctx=...)` (no single endpoint env var; it depends on the social pipeline configuration).
- **Signals it catches:** narrative ignition, crowd attention, contrarian flags, echo-chamber conditions.
- **What it misses:** hidden positioning; whales can front-run social.
- **Tuning knobs:** increase `weights.social` in memecoin/narrative regimes; reduce when market is purely macro.

#### `market-sentiment` (domain: social)

- **Data:** HTTP endpoint (`B1E55ED_SENTIMENT_URL` / `SENTIMENT_URL`).
- **Signals it catches:** broad market risk appetite (fear/greed), and optional CT sentiment.
- **What it misses:** asset-specific catalysts.
- **Tuning knobs:** raise `weights.social` when cross-asset “risk-on/risk-off” dominates.

#### `technical-analysis` (domain: technical)

- **Data:** HTTP endpoint (`B1E55ED_TA_URL` / `TA_URL`) returning precomputed TA values for your universe.
- **Signals it catches:** trend/mean reversion structure, support/resistance context, strength.
- **What it misses:** regime shifts from news/flows; fakeouts from low liquidity.
- **Tuning knobs:** raise `weights.technical` in clean structure regimes; lower in chop/news-driven periods.

#### `orderbook-depth` (domain: technical)

- **Data:** HTTP endpoint (`B1E55ED_ORDERBOOK_URL` / `ORDERBOOK_URL`).
- **Signals it catches:** liquidity cliffs, imbalance, fragility before squeezes/dumps.
- **What it misses:** slow-moving macro context.
- **Tuning knobs:** raise `weights.technical` for short-horizon trading; reduce if you don’t have good orderbook data.

#### `price-alerts` (domain: technical)

- **Data:** HTTP endpoint (`B1E55ED_PRICE_WS_URL` / `PRICE_WS_URL`), polled every minute.
- **Signals it catches:** fast price state (price/bid/ask/venue) to keep “technical state” fresh.
- **What it misses:** deeper context; it’s just a thin feed.
- **Tuning knobs:** if the endpoint is unreliable, consider lowering `weights.technical` until stable.

#### `market-events` (domain: events)

- **Data:** HTTP endpoint (`B1E55ED_EVENTS_URL` / `EVENTS_URL`) returning catalysts and scores.
- **Signals it catches:** discrete catalysts, news shocks, event clusters.
- **What it misses:** longer-term flows/structure.
- **Tuning knobs:** increase `weights.events` when catalysts dominate; keep low in normal conditions.

---

## 3) Symbol packs (copy/paste `config/user.yaml` snippets)

b1e55ed reads config from (in order):

1. `config/default.yaml`
2. `config/presets/<preset>.yaml`
3. `config/user.yaml` (your overlay)

### BTC Core (Bitcoin maximalist)

High conviction; emphasize curator + onchain + tradfi.

```yaml
# config/user.yaml
preset: custom

universe:
  symbols: ["BTC"]

weights:
  curator: 0.30
  onchain: 0.25
  tradfi: 0.30
  social: 0.05
  technical: 0.07
  events: 0.03
```

### Solana Ecosystem (high beta, narrative-driven)

Emphasize social + onchain; keep tradfi small.

```yaml
# config/user.yaml
preset: custom

universe:
  symbols: ["SOL", "JTO", "PYTH", "WIF", "BONK"]

weights:
  curator: 0.20
  onchain: 0.30
  tradfi: 0.05
  social: 0.30
  technical: 0.10
  events: 0.05
```

### Multi-Asset Degen (broad exposure, faster signals)

Balanced, with a bit more technical for responsiveness.

```yaml
# config/user.yaml
preset: custom

universe:
  symbols: ["BTC", "ETH", "SOL", "HYPE", "SUI", "AVAX"]

weights:
  curator: 0.20
  onchain: 0.25
  tradfi: 0.15
  social: 0.15
  technical: 0.20
  events: 0.05
```

### TradFi Overlay (CME basis + ETF flows)

TradFi-heavy for BTC/ETH; keep others secondary.

```yaml
# config/user.yaml
preset: custom

universe:
  symbols: ["BTC", "ETH"]

weights:
  curator: 0.15
  onchain: 0.15
  tradfi: 0.45
  social: 0.10
  technical: 0.10
  events: 0.05
```

> If you copy one of these packs and a domain stays empty in practice, it’s usually because the underlying producers for that domain are missing endpoints and producing no events.

---

## 4) Weight tuning guide

### The rule: weights must sum to 1.0

Domain weights (`weights.*`) must sum to **1.0** (validated with ±0.001 tolerance).

### When to increase/decrease each domain

- **Increase `technical`** when markets trend cleanly or respect ranges; reduce when catalysts dominate or liquidity is thin.
- **Increase `social`** in narrative regimes (memecoins, ecosystem rotations, CT-driven pumps); reduce when macro/basis dominates.
- **Increase `onchain`** in accumulation/distribution phases, when whale behavior leads price.
- **Increase `tradfi`** for BTC/ETH when CME basis, ETF flows, and funding regimes are “the game.”
- **Increase `events`** when catalysts (listings, unlocks, court decisions, ETF approvals) are driving discontinuities.
- **Increase `curator`** when you have real discretionary edge and you’re actively curating signals.

### Conviction thresholds (decision policy)

There is **no `conviction_threshold` config key** in this version. The default decision thresholds are currently coded in `engine/brain/decision.py`:

- PCS **>= 60** → enter (moderate)
- PCS **>= 75** → enter (strong)
- PCS **>= 90** → enter (approval required flag)

If you need configurable thresholds, you’ll need to swap the decision policy or patch the defaults.

---

## 5) Producer health & debugging

### Quick checks

- `b1e55ed status`
  - Look for: domains missing features, repeated producer failures, kill switch level, last cycle timestamps.

- `b1e55ed producers list`
  - Lists producers tracked in the `producer_health` table (health metadata).

- `b1e55ed cycle --full`
  - Runs a full cycle including slower producers (the CLI also runs “fast” producers by default).

### What “quarantined” means

During `b1e55ed cycle`, producers that fail repeatedly can be marked as **quarantined** in the database (`producer_health.quarantined_until`). When quarantined, a producer is skipped and reported as such.

How to recover:

- Fix the root cause (missing endpoint env var, expired credentials, endpoint returning 4xx/5xx).
- Re-run a cycle and verify the producer returns to **OK**.

(Quarantine state is stored in `data/brain.db` in the `producer_health` table.)

### Logs & data locations

- DB: `data/brain.db`
- Learned weight overlay (optional): `data/learned_weights.yaml`

---

## 6) Advanced: custom weights from backtest / learning

### Walk-forward backtest

The CLI supports walk-forward backtests (price-only strategies) via:

```bash
b1e55ed backtest walkforward \
  --strategy combined \
  --prices ./data/BTC.csv
```

This is primarily for strategy research and statistical sanity checks.

### Learned weights overlay (domain weights)

b1e55ed can also apply an optional learned weights overlay at:

- `data/learned_weights.yaml`

This file (surface 3) overrides `weights.*` after presets/user config are loaded.

Format:

```yaml
weights:
  curator: 0.25
  onchain: 0.25
  tradfi: 0.20
  social: 0.15
  technical: 0.10
  events: 0.05
```

To keep things simple operationally:

- Use `config/user.yaml` while iterating.
- When you have stable weights from a study/learning loop, write them to `data/learned_weights.yaml` for a clean separation between *operator intent* and *learned overlay*.
