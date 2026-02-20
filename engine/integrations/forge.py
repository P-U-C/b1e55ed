"""engine.integrations.forge

Pure-Python vanity address grinder (fallback when Rust binary unavailable).
~50K candidates/sec on a single core. Use the Rust grinder for production.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any


def _keccak256(data: bytes) -> bytes:
    """Keccak-256 hash."""

    # Note: Python's hashlib.sha3_256 is NOT keccak256.
    try:
        from eth_utils.crypto import keccak

        return keccak(data)
    except Exception:
        pass

    try:
        from Crypto.Hash import keccak as crypto_keccak

        k = crypto_keccak.new(digest_bits=256)
        k.update(data)
        return k.digest()
    except Exception:
        pass

    try:
        import sha3

        return sha3.keccak_256(data).digest()
    except Exception as e:
        raise ImportError("No keccak256 implementation available. Install eth-account or pycryptodome.") from e


def grind(prefix: str = "b1e55ed", *, report_interval: float = 1.0) -> Generator[dict[str, Any], None, None]:
    """Grind for a vanity Ethereum address.

    Yields progress dicts and finally a 'found' dict.

    Uses eth_account for key generation.
    """

    try:
        from eth_account import Account
    except Exception as e:
        raise ImportError("eth-account required for Python grinder. Install with: uv sync --extra eas") from e

    prefix_lower = prefix.lower()
    candidates = 0
    start = time.monotonic()
    last_report = start

    while True:
        acct = Account.create()
        addr = acct.address.lower()
        pk = acct.key.hex()

        candidates += 1

        # Check prefix (skip "0x")
        if addr[2 : 2 + len(prefix_lower)] == prefix_lower:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            yield {
                "type": "found",
                "address": acct.address,
                "private_key": pk,
                "candidates": candidates,
                "elapsed_ms": elapsed_ms,
            }
            return

        now = time.monotonic()
        if now - last_report >= report_interval:
            elapsed_ms = int((now - start) * 1000)
            rate = int(candidates / (now - start)) if now > start else 0
            yield {
                "type": "progress",
                "candidates": candidates,
                "elapsed_ms": elapsed_ms,
                "rate": rate,
            }
            last_report = now
