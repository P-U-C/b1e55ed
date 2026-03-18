"""engine.social.filters.preprocessing

Deduplicate, normalize symbols, filter garbage from raw collector output.
"""

from __future__ import annotations

from typing import Any


def preprocess(raw_signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate, normalize symbols, filter garbage."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []

    for sig in raw_signals:
        symbol = str(sig.get("symbol") or "").upper().strip()
        source = str(sig.get("source") or "").strip()

        if not symbol:
            continue

        key = (symbol, source)
        if key in seen:
            continue
        seen.add(key)

        sig["symbol"] = symbol
        out.append(sig)

    return out
