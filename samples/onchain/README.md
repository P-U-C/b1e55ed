# On-Chain Intelligence Pack

Blockchain data analysis for whale tracking, smart money detection, and DEX flow monitoring.

---

## What's Included

1. **Whale Tracker** - Large wallet accumulation/distribution (Allium API)
2. **Cluster Detector** - Sub-wallet identification and coordinated buying
3. **DEX Flow Analyzer** - Real-time liquidity and trade flow (Uniswap, Jupiter, etc.)

---

## Use Cases

### Whale Wallet Tracking
Follow wallets with proven track records (via karma hit rate validation).

**Signal:** Whale wallet buys 100+ ETH worth of token = accumulation
**Conviction:** Scaled by wallet's historical hit rate (tracked in karma system)
**Risk:** Whales dump on retail (need exit strategy)

### Smart Money Cluster Detection
Identify coordinated accumulation across sub-wallets (one entity, multiple addresses).

**Pattern:** 3+ wallets funded from same source all buy same token within 24h
**Signal:** Coordinated accumulation = informed buying
**Conviction:** Higher for known clusters (tracked via graph analysis)

### DEX Liquidity Monitoring
Track when large liquidity gets added/removed (precedes moves).

**Signal:** 
- Liquidity added = expect range-bound (MMs farming)
- Liquidity removed = expect volatility (MMs stepping aside)

**Use:** Avoid low-liquidity environments (wide slippage, manipulation risk)

---

## API Requirements

### Allium (On-Chain Data)
- **Service:** Allium API (allium.so)
- **Cost:** Free tier available (limited queries)
- **Rate Limit:** 1 request/second
- **Auth:** API key required
- **Env:** `ALLIUM_API_KEY`
- **Chains:** Ethereum, Solana, Bitcoin, Base, Arbitrum, Polygon, +150 more

**Key Endpoints:**
- Wallet balances
- Transaction history
- Wallet P&L
- Token holders

### Etherscan (Alternative for Ethereum)
- **Service:** Etherscan API
- **Cost:** Free tier (5 calls/sec)
- **Auth:** API key required
- **Chains:** Ethereum mainnet only

### Solscan (Alternative for Solana)
- **Service:** Solscan API
- **Cost:** Free tier available
- **Auth:** API key required
- **Chains:** Solana only

---

## Example: Whale Accumulation Tracker

```python
"""Track whale wallet accumulation via Allium API."""
import requests
from datetime import datetime, timedelta
from b1e55ed.types import Signal

class WhaleTrackerProducer:
    def __init__(self, config: dict):
        self.allium_key = config["allium_api_key"]
        self.whale_threshold = config.get("whale_threshold_usd", 100_000)  # $100K+
        self.tracked_wallets = config.get("tracked_wallets", [])
    
    def produce(self, symbol: str) -> Signal:
        """Check if tracked whales are accumulating."""
        try:
            accumulation_count = 0
            accumulation_usd = 0
            whale_details = []
            
            for wallet in self.tracked_wallets:
                buys = self._fetch_recent_buys(wallet, symbol)
                if buys["total_usd"] > self.whale_threshold:
                    accumulation_count += 1
                    accumulation_usd += buys["total_usd"]
                    whale_details.append({
                        "wallet": wallet[:10] + "...",
                        "amount_usd": buys["total_usd"]
                    })
            
            if accumulation_count >= 2:  # 2+ whales buying
                conviction = min(8 + accumulation_count, 10)
                return Signal(
                    symbol=symbol,
                    signal="long",
                    conviction=conviction,
                    rationale=(
                        f"{accumulation_count} whale wallets accumulated "
                        f"${accumulation_usd:,.0f} of {symbol} in 24h"
                    ),
                    producer="WhaleTracker",
                    timestamp=int(datetime.now().timestamp()),
                    metadata={
                        "whale_count": accumulation_count,
                        "total_usd": accumulation_usd,
                        "whales": whale_details
                    }
                )
            else:
                return self._neutral(symbol, "No significant whale accumulation")
        
        except Exception as e:
            return self._neutral(symbol, f"Error: {str(e)}")
    
    def _fetch_recent_buys(self, wallet: str, symbol: str) -> dict:
        """Fetch recent buys for wallet via Allium."""
        url = "https://api.allium.so/api/v1/developer/wallet/transactions"
        headers = {"apiKey": self.allium_key}
        payload = {
            "chain": "ethereum",  # Or detect from symbol
            "address": wallet,
            "timeRange": "24h"
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        data = response.json()
        
        # Filter to buys of this symbol
        buys = [
            tx for tx in data.get("transactions", [])
            if tx.get("token_symbol") == symbol and tx.get("type") == "buy"
        ]
        
        total_usd = sum(tx.get("value_usd", 0) for tx in buys)
        
        return {"total_usd": total_usd, "count": len(buys)}
    
    def _neutral(self, symbol: str, rationale: str) -> Signal:
        return Signal(
            symbol=symbol,
            signal="neutral",
            conviction=0,
            rationale=rationale,
            producer="WhaleTracker",
            timestamp=int(datetime.now().timestamp()),
            metadata={}
        )
```

**Config:**
```yaml
brain:
  producers:
    - name: whale_tracker
      module: b1e55ed.producers.whale_tracker
      class: WhaleTrackerProducer
      enabled: true
      config:
        allium_api_key: ${ALLIUM_API_KEY}
        whale_threshold_usd: 100000
        tracked_wallets:
          - "0xabc123..."  # Known whale 1
          - "0xdef456..."  # Known whale 2
```

---

## Example: Cluster Detector

```python
"""Detect coordinated buying across sub-wallets."""
import requests
from collections import defaultdict
from b1e55ed.types import Signal

class ClusterDetector:
    def __init__(self, config: dict):
        self.allium_key = config["allium_api_key"]
        self.min_cluster_size = config.get("min_cluster_size", 3)
    
    def produce(self, symbol: str) -> Signal:
        """Detect if wallet cluster is accumulating."""
        try:
            # 1. Fetch recent buyers of this token
            recent_buyers = self._fetch_recent_buyers(symbol)
            
            # 2. Group by funding source (cluster detection)
            clusters = self._detect_clusters(recent_buyers)
            
            # 3. Check for coordinated accumulation
            for cluster_id, wallets in clusters.items():
                if len(wallets) >= self.min_cluster_size:
                    total_bought = sum(w["amount_usd"] for w in wallets)
                    
                    return Signal(
                        symbol=symbol,
                        signal="long",
                        conviction=9,
                        rationale=(
                            f"{len(wallets)} coordinated wallets accumulated "
                            f"${total_bought:,.0f} of {symbol} in 24h "
                            f"(cluster: {cluster_id[:10]}...)"
                        ),
                        producer="ClusterDetector",
                        timestamp=int(datetime.now().timestamp()),
                        metadata={
                            "cluster_size": len(wallets),
                            "total_usd": total_bought,
                            "cluster_id": cluster_id
                        }
                    )
            
            return self._neutral(symbol, "No cluster accumulation detected")
        
        except Exception as e:
            return self._neutral(symbol, f"Error: {str(e)}")
    
    def _fetch_recent_buyers(self, symbol: str) -> list[dict]:
        """Fetch wallets that bought this token recently."""
        # Implementation: Query Allium for token transactions
        # Filter to buys in last 24h
        # Return list of {wallet, amount_usd, timestamp}
        raise NotImplementedError
    
    def _detect_clusters(self, buyers: list[dict]) -> dict[str, list[dict]]:
        """Group wallets by funding source (cluster ID)."""
        clusters = defaultdict(list)
        
        for buyer in buyers:
            # Trace funding source (first deposit to this wallet)
            funding_source = self._trace_funding_source(buyer["wallet"])
            clusters[funding_source].append(buyer)
        
        return clusters
    
    def _trace_funding_source(self, wallet: str) -> str:
        """Find the wallet that first funded this address."""
        # Implementation: Query transaction history
        # Find first incoming transaction
        # Return sender address
        raise NotImplementedError
```

---

## Example: DEX Liquidity Monitor

```python
"""Track DEX liquidity adds/removes."""
import requests
from b1e55ed.types import Signal

class DEXLiquidityProducer:
    def __init__(self, config: dict):
        self.dex_api_url = config.get("dex_api_url", "https://api.dexscreener.com/latest")
    
    def produce(self, symbol: str) -> Signal:
        """Monitor liquidity changes for token."""
        try:
            liquidity_change = self._fetch_liquidity_change(symbol)
            
            if liquidity_change["pct_change"] < -20:  # 20%+ liquidity removed
                return Signal(
                    symbol=symbol,
                    signal="short",  # MMs exiting = volatility incoming
                    conviction=7,
                    rationale=(
                        f"{symbol} liquidity removed: "
                        f"{liquidity_change['pct_change']:.1f}% in 24h "
                        f"(expect volatility)"
                    ),
                    producer="DEXLiquidity",
                    timestamp=int(datetime.now().timestamp()),
                    metadata=liquidity_change
                )
            elif liquidity_change["pct_change"] > 50:  # 50%+ liquidity added
                return Signal(
                    symbol=symbol,
                    signal="neutral",  # MMs farming = range-bound
                    conviction=0,
                    rationale=(
                        f"{symbol} liquidity added: "
                        f"+{liquidity_change['pct_change']:.1f}% in 24h "
                        f"(expect range-bound)"
                    ),
                    producer="DEXLiquidity",
                    timestamp=int(datetime.now().timestamp()),
                    metadata=liquidity_change
                )
            else:
                return self._neutral(symbol, "Liquidity stable")
        
        except Exception as e:
            return self._neutral(symbol, f"Error: {str(e)}")
    
    def _fetch_liquidity_change(self, symbol: str) -> dict:
        """Fetch 24h liquidity change from DEX aggregator."""
        url = f"{self.dex_api_url}/dex/tokens/{symbol}"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        # Extract liquidity data
        liquidity_now = data.get("liquidity", {}).get("usd", 0)
        liquidity_24h_ago = data.get("liquidity24h", {}).get("usd", 0)
        
        pct_change = ((liquidity_now - liquidity_24h_ago) / liquidity_24h_ago) * 100
        
        return {
            "liquidity_now": liquidity_now,
            "liquidity_24h_ago": liquidity_24h_ago,
            "pct_change": pct_change
        }
```

---

## Best Practices

### 1. Validate Whale Quality
Not all whales have alpha. Track hit rates via karma system:
- Which wallets are worth following (60%+ win rate)
- Which wallets are exit liquidity (dumps on retail)
- Update tracked wallet list based on performance

### 2. Cluster Graph Analysis
Build graph of wallet relationships over time:
- Funding sources (who funded this wallet)
- Trading partners (who do they send/receive from)
- Temporal patterns (do they trade together)

### 3. Cross-Chain Correlation
Same entity often operates across multiple chains:
- Check for address similarity (vanity addresses)
- Look for simultaneous actions (buy ETH on L1, buy SOL on Solana)
- Trace bridge transactions

### 4. Combine On-Chain + Social
Most powerful when they confirm each other:
- TikTok buzz + whale accumulation = strong long
- Twitter hype + whale distribution = exit liquidity (fade)

---

## Validation

**Expected metrics:**
- Whale tracking: 55-65% win rate (better than random)
- Cluster detection: 70%+ win rate (coordinated buying = informed)
- Liquidity monitoring: Useful for risk management (not profit signal)

**Red flags:**
- Whale wallet dumps immediately after buying (bot, not smart money)
- Cluster wallets all exit same day (coordinated dump, not accumulation)
- No on-chain confirmation for social buzz (pump fake)

---

## Data Sources

### Allium API
- **Pros:** Multi-chain, comprehensive, good API
- **Cons:** Rate limited, free tier restrictive
- **Best for:** Ethereum, Solana, Base

### Dune Analytics
- **Pros:** SQL queries, community dashboards
- **Cons:** Slow, not real-time
- **Best for:** Historical analysis, complex queries

### The Graph (Subgraphs)
- **Pros:** Decentralized, fast, protocol-specific
- **Cons:** Per-protocol setup, learning curve
- **Best for:** DEX-specific queries (Uniswap, Curve)

### Blockchain Nodes (Direct)
- **Pros:** Real-time, no rate limits (your node)
- **Cons:** Infrastructure cost, complexity
- **Best for:** High-frequency monitoring

---

## Roadmap

**Planned additions:**
- NFT whale tracking (OpenSea, Blur)
- Staking/unstaking flows (governance signals)
- Bridge flows (L1 ↔ L2 capital movement)
- DAO treasury movements (protocol insider trading)

---

*Last updated: 2026-02-19*
