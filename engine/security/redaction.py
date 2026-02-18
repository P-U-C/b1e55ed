"""engine.security.redaction

Secret redaction helpers.

These are deliberately pragmatic: redact likely secrets before anything hits logs.
"""

from __future__ import annotations

import copy
import re
from typing import Any


_REDACTION_PATTERNS: list[tuple[str, str]] = [
    # Generic key/value
    (r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*[^\s\"']+", "[REDACTED]"),
    # OpenAI
    (r"sk-proj-[a-zA-Z0-9]{20,}", "[REDACTED]"),
    (r"sk-[a-zA-Z0-9]{20,}", "[REDACTED]"),
    # Anthropic
    (r"sk-ant-api\d+-[a-zA-Z0-9]+", "[REDACTED]"),
    # xAI
    (r"xai-[a-zA-Z0-9]{20,}", "[REDACTED]"),
    # JWT
    (r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+", "[REDACTED]"),
    # Private key / secret hex
    (r"0x[a-fA-F0-9]{64}", "[REDACTED]"),
    # Solana base58-ish addresses (very rough, avoids false positives by requiring length)
    (r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b", "[REDACTED]"),
    # ETH address (not secret, but treated as sensitive in logs)
    (r"\b0x[a-fA-F0-9]{40}\b", "[REDACTED]"),
]

_SENSITIVE_FIELD_NAMES = {
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "private_key",
    "seed",
    "mnemonic",
    "auth",
    "authorization",
}


def redact_secrets(text: str) -> str:
    out = text
    for pattern, repl in _REDACTION_PATTERNS:
        out = re.sub(pattern, repl, out)
    return out


def sanitize_for_log(data: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy and redact sensitive fields + embedded secrets."""

    def _walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            new: dict[str, Any] = {}
            for k, v in obj.items():
                if str(k).lower() in _SENSITIVE_FIELD_NAMES:
                    new[k] = "[REDACTED]"
                else:
                    new[k] = _walk(v)
            return new
        if isinstance(obj, list):
            return [_walk(v) for v in obj]
        if isinstance(obj, tuple):
            return [_walk(v) for v in obj]
        if isinstance(obj, str):
            return redact_secrets(obj)
        return obj

    return _walk(copy.deepcopy(data))
