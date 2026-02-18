"""engine.core.allowlists

Configurable allowlists.

In execution, permissiveness is a bug.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_ALLOWED_VENUES = frozenset({"hyperliquid", "binance", "coinbase"})
DEFAULT_ALLOWED_CHAINS = frozenset({"ethereum", "solana", "hyperevm", "base", "arbitrum"})
DEFAULT_ALLOWED_TOKENS = frozenset({"BTC", "ETH", "SOL", "HYPE", "SUI"})


@dataclass(frozen=True, slots=True)
class Allowlists:
    venues: frozenset[str] = DEFAULT_ALLOWED_VENUES
    chains: frozenset[str] = DEFAULT_ALLOWED_CHAINS
    tokens: frozenset[str] = DEFAULT_ALLOWED_TOKENS

    def venue_allowed(self, venue: str) -> bool:
        return str(venue).lower() in self.venues

    def chain_allowed(self, chain: str) -> bool:
        return str(chain).lower() in self.chains

    def token_allowed(self, token: str) -> bool:
        return str(token).upper() in self.tokens
