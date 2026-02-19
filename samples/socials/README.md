# Social Intelligence Pack

Track social media buzz for early meme coin detection and narrative trend tracking.

---

## What's Included

1. **TikTok Scraper** - Hashtag mentions via Apify
2. **Twitter Search** - Mention counter (when bird works)
3. **Reddit Sentiment** - Subreddit activity tracker

---

## Use Cases

### Early Meme Coin Detection
Track sudden spikes in TikTok/Twitter mentions before price pumps.

**Signal:** Asset mentioned 50+ times on TikTok in 24h = early buzz
**Conviction:** Scaled by velocity (mentions per hour)
**Risk:** High false positives (most memes dump fast)

### Narrative Trend Tracking
Identify which crypto narratives are gaining traction.

**Examples:** "AI agents", "DePIN", "RWA", "Solana memes"
**Signal:** Hashtag velocity + engagement metrics
**Use:** Position for narrative rotations before consensus

### Influencer Signal Extraction
Track specific accounts for alpha (with hit rate validation).

**Examples:** @lookonchain (whale moves), @unusual_whales (flows)
**Signal:** New post from trusted source
**Validation:** Karma system tracks which accounts actually have alpha

---

## API Requirements

### TikTok (via Apify)
- **Service:** Apify `clockworks~free-tiktok-scraper`
- **Cost:** Free tier ~$5/month credits
- **Rate Limit:** Credit-based (40 results = ~1 credit)
- **Auth:** API key required
- **Env:** `APIFY_API_KEY`

### Twitter (Direct API - paid)
- **Service:** Twitter API v2
- **Cost:** $100/month for Basic tier
- **Rate Limit:** 10K tweets/month
- **Auth:** Bearer token
- **Env:** `TWITTER_BEARER_TOKEN`

### Twitter (via bird CLI - free but brittle)
- **Service:** Local authentication
- **Cost:** Free
- **Rate Limit:** None (uses your account)
- **Auth:** Cookie-based (breaks frequently)
- **Status:** ⚠️ Often broken, not reliable

### Reddit (via PRAW)
- **Service:** Reddit API
- **Cost:** Free
- **Rate Limit:** 60 req/min
- **Auth:** Client ID + secret
- **Env:** `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`

---

## Example: TikTok Meme Detector

```python
"""Detect trending crypto memes on TikTok."""
import requests
import time
from b1e55ed.types import Signal

class TikTokMemeProducer:
    def __init__(self, config: dict):
        self.apify_token = config["apify_token"]
        self.mention_threshold = config.get("mention_threshold", 50)
    
    def produce(self, symbol: str) -> Signal:
        """Check if symbol is trending on TikTok."""
        mentions = self._fetch_mentions(symbol)
        
        if mentions >= self.mention_threshold:
            conviction = min(int(mentions / 10), 10)
            return Signal(
                symbol=symbol,
                signal="long",
                conviction=conviction,
                rationale=f"{symbol} trending on TikTok: {mentions} mentions in 24h",
                producer="TikTokMeme",
                timestamp=int(time.time()),
                metadata={"mentions": mentions, "source": "tiktok"}
            )
        else:
            return Signal(
                symbol=symbol,
                signal="neutral",
                conviction=0,
                rationale=f"{symbol} low TikTok activity: {mentions} mentions",
                producer="TikTokMeme",
                timestamp=int(time.time()),
                metadata={"mentions": mentions}
            )
    
    def _fetch_mentions(self, symbol: str) -> int:
        """Count TikTok hashtag mentions."""
        url = "https://api.apify.com/v2/acts/clockworks~free-tiktok-scraper/runs"
        payload = {
            "searchQueries": [f"#{symbol.lower()} crypto"],
            "resultsPerPage": 40
        }
        headers = {"Authorization": f"Bearer {self.apify_token}"}
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        data = response.json()
        
        return len(data.get("items", []))
```

**Config:**
```yaml
brain:
  producers:
    - name: tiktok_meme
      module: b1e55ed.producers.tiktok_meme
      class: TikTokMemeProducer
      enabled: true
      config:
        apify_token: ${APIFY_API_KEY}
        mention_threshold: 50
```

---

## Example: Twitter Mention Counter

```python
"""Count Twitter mentions for crypto assets."""
import requests
from b1e55ed.types import Signal

class TwitterMentionProducer:
    def __init__(self, config: dict):
        self.bearer_token = config["bearer_token"]
        self.threshold = config.get("threshold", 100)
    
    def produce(self, symbol: str) -> Signal:
        """Count recent Twitter mentions."""
        mentions = self._count_mentions(symbol)
        
        if mentions >= self.threshold:
            conviction = min(int(mentions / 20), 10)
            return Signal(
                symbol=symbol,
                signal="long",
                conviction=conviction,
                rationale=f"{symbol} trending on Twitter: {mentions} mentions in 24h",
                producer="TwitterMention",
                timestamp=int(time.time()),
                metadata={"mentions": mentions}
            )
        else:
            return Signal(
                symbol=symbol,
                signal="neutral",
                conviction=0,
                rationale=f"{symbol} low Twitter activity: {mentions} mentions",
                producer="TwitterMention",
                timestamp=int(time.time()),
                metadata={"mentions": mentions}
            )
    
    def _count_mentions(self, symbol: str) -> int:
        """Query Twitter API for recent mentions."""
        url = "https://api.twitter.com/2/tweets/search/recent"
        params = {
            "query": f"${symbol} OR #{symbol} crypto -is:retweet",
            "max_results": 100
        }
        headers = {"Authorization": f"Bearer {self.bearer_token}"}
        
        response = requests.get(url, params=params, headers=headers, timeout=30)
        data = response.json()
        
        return data.get("meta", {}).get("result_count", 0)
```

---

## Best Practices

### 1. Filter Noise
Social signals are loud but often wrong. Require:
- Velocity spike (not just absolute volume)
- Cross-platform confirmation (TikTok + Twitter)
- Volume/price confirmation (on-chain follows social)

### 2. Track Hit Rates
Use karma system to validate which social signals work:
- Which platforms have alpha (TikTok vs Twitter vs Reddit)
- Which accounts are worth tracking
- Which hashtags precede pumps vs dumps

### 3. Avoid Echo Chambers
Coordinated shilling looks like organic buzz. Check:
- Account ages (new accounts = bots)
- Engagement quality (generic comments = fake)
- On-chain confirmation (is smart money actually buying?)

### 4. Cost Control
Social APIs burn credits fast. Optimize:
- Cache results (5min TTL)
- Batch requests (check multiple symbols together)
- Monitor costs (set monthly budget alerts)

---

## Validation

**Paper trade first:** Social signals are high-variance. Run 30 days paper trading before risking capital.

**Expected metrics:**
- Win rate: 40-50% (lots of losers, big winners matter)
- Average hold: 1-3 days (meme pumps are fast)
- Risk/reward: 3:1 minimum (risk $1 to make $3+)
- Sharpe: 0.3-0.5 (noisy but occasional home runs)

**Red flags:**
- 100% hit rate = survivorship bias (only counting winners)
- No losers = not actually trading these signals
- Every signal becomes a pump = confirmation bias

---

## Roadmap

**Planned additions:**
- Discord server monitors (especially CT alpha groups)
- Telegram channel scrapers (crypto-native)
- YouTube video tracker (LaTeX sentiment analysis)
- Instagram influencer mentions

---

*Last updated: 2026-02-19*
