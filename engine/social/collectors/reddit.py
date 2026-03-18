"""engine.social.collectors.reddit

Reddit /r/cryptocurrency collector (free, just needs User-Agent).

Scrapes hot posts for symbol mentions and derives sentiment from upvote ratios.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from engine.social.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

_SUBREDDITS = [
    "cryptocurrency",
    "CryptoMarkets",
]

_USER_AGENT = "b1e55ed/1.0 (social-intel-pipeline)"


class RedditCollector(BaseCollector):
    """Collect sentiment from Reddit crypto subreddits."""

    name = "reddit"

    def collect(self, symbols: list[str]) -> list[dict[str, Any]]:
        sym_set = {s.upper() for s in symbols}
        results: list[dict[str, Any]] = []

        for subreddit in _SUBREDDITS:
            posts = _fetch_subreddit(subreddit)
            for post in posts:
                title = post.get("title", "")
                score = post.get("score", 0)
                upvote_ratio = post.get("upvote_ratio", 0.5)

                matched = _match_symbols(title, sym_set)
                if not matched:
                    continue

                # Sentiment from upvote ratio: 0.5 → 0, 1.0 → 1, 0.0 → -1
                sentiment = (upvote_ratio - 0.5) * 2

                for sym in matched:
                    results.append(
                        {
                            "symbol": sym,
                            "sentiment": round(sentiment, 4),
                            "source": self.name,
                            "volume": max(score, 1),
                        }
                    )

        # Dedupe: keep highest-volume per symbol
        by_sym: dict[str, dict[str, Any]] = {}
        for r in results:
            sym = r["symbol"]
            if sym not in by_sym or r["volume"] > by_sym[sym]["volume"]:
                by_sym[sym] = r

        out = list(by_sym.values())
        logger.info("reddit_collected", extra={"posts_scanned": len(results), "signals": len(out)})
        return out


def _fetch_subreddit(subreddit: str) -> list[dict[str, Any]]:
    """Fetch hot posts from a subreddit."""
    url = f"https://www.reddit.com/r/{subreddit}/hot.json"
    try:
        resp = httpx.get(
            url,
            params={"limit": "50"},
            headers={"User-Agent": _USER_AGENT},
            timeout=10,
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.warning("reddit_fetch_failed", extra={"subreddit": subreddit}, exc_info=True)
        return []

    posts = []
    children = data.get("data", {}).get("children", [])
    for child in children:
        post_data = child.get("data", {})
        posts.append(
            {
                "title": post_data.get("title", ""),
                "score": post_data.get("score", 0),
                "upvote_ratio": post_data.get("upvote_ratio", 0.5),
            }
        )
    return posts


def _match_symbols(text: str, sym_set: set[str]) -> list[str]:
    """Find which symbols from sym_set appear in text."""
    text_upper = text.upper()
    matched = []
    for sym in sym_set:
        if re.search(rf"\b{re.escape(sym)}\b", text_upper):
            matched.append(sym)

    # Check full names
    _name_map = {
        "BITCOIN": "BTC",
        "ETHEREUM": "ETH",
        "SOLANA": "SOL",
        "HYPERLIQUID": "HYPE",
    }
    for name, sym in _name_map.items():
        if name in text_upper and sym in sym_set and sym not in matched:
            matched.append(sym)

    return matched
