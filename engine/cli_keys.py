"""engine.cli_keys

Key management subcommands for the b1e55ed CLI.

Design goals:
- Minimal dependencies (urllib only).
- Graceful failure: never raise on network errors; report per-provider status.
- Machine-readable JSON for automation.

Known key slots are defined in :data:`KNOWN_KEY_SLOTS`.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from engine.security.keystore import Keystore

KNOWN_KEY_SLOTS: tuple[str, ...] = (
    "hyperliquid.api_key",
    "hyperliquid.api_secret",
    "allium.api_key",
    "nansen.api_key",
    "reddit.client_id",
    "apify.token",
)


@dataclass(frozen=True)
class ProviderCheck:
    provider: str
    configured: bool
    status: str  # healthy|warning|critical|missing
    message: str


def _get_optional(keystore: Keystore, name: str) -> str | None:
    try:
        return keystore.get(name)
    except KeyError:
        return None


def cmd_keys_list(*, keystore: Keystore, as_json: bool = False) -> int:
    rows: list[dict[str, Any]] = []
    for name in KNOWN_KEY_SLOTS:
        configured = _get_optional(keystore, name) is not None
        rows.append({"name": name, "configured": configured})

    if as_json:
        print(json.dumps({"keys": rows}, indent=2, sort_keys=True))
        return 0

    max_name = max(len(r["name"]) for r in rows) if rows else 10
    for r in rows:
        mark = "✅" if r["configured"] else "❌"
        print(f"{mark} {r['name']:<{max_name}}  {'configured' if r['configured'] else 'not set'}")
    return 0


def cmd_keys_set(*, keystore: Keystore, name: str, value: str, as_json: bool = False) -> int:
    if not name:
        raise ValueError("name is required")
    if not value:
        raise ValueError("value is required")

    keystore.set(str(name), str(value))

    if as_json:
        print(json.dumps({"ok": True, "name": str(name)}, indent=2, sort_keys=True))
        return 0

    unknown = " (unknown slot)" if str(name) not in KNOWN_KEY_SLOTS else ""
    print(f"stored {name}{unknown}")
    return 0


def cmd_keys_remove(*, keystore: Keystore, name: str, as_json: bool = False) -> int:
    try:
        removed = keystore.remove_key(str(name))
    except Exception as e:
        if as_json:
            print(json.dumps({"ok": False, "name": str(name), "error": str(e)}, indent=2, sort_keys=True))
            return 1
        print(f"error: {e}", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps({"ok": True, "name": str(name), "removed": bool(removed)}, indent=2, sort_keys=True))
        return 0

    if removed:
        print(f"removed {name}")
    else:
        print(f"{name} not found")
    return 0


def _http_json(
    *,
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout_s: float = 5.0,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[int, dict[str, Any] | None]:
    data: bytes | None = None
    req_headers = {"User-Agent": "b1e55ed-cli/keys-test"}
    if headers:
        req_headers.update(headers)

    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url=url, data=data, method=method, headers=req_headers)
    try:
        with urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
            status = int(getattr(resp, "status", 200))
            if not raw:
                return status, None
            try:
                return status, json.loads(raw.decode("utf-8"))
            except Exception:
                return status, None
    except urllib.error.HTTPError as e:
        status = int(getattr(e, "code", 0) or 0)
        try:
            raw = e.read()
            data_obj = json.loads(raw.decode("utf-8")) if raw else None
        except Exception:
            data_obj = None
        return status, data_obj


def _check_hyperliquid(*, keystore: Keystore, urlopen: Callable[..., Any]) -> ProviderCheck:
    api_key = _get_optional(keystore, "hyperliquid.api_key")
    api_secret = _get_optional(keystore, "hyperliquid.api_secret")
    if not api_key or not api_secret:
        return ProviderCheck("hyperliquid", configured=False, status="missing", message="not configured")

    status, payload = _http_json(
        url="https://api.hyperliquid.xyz/info",
        method="POST",
        body={"type": "meta"},
        urlopen=urlopen,
    )
    if 200 <= status < 300:
        universe = None
        if isinstance(payload, dict):
            universe = payload.get("universe")
        sym_count = len(universe) if isinstance(universe, list) else None
        extra = f" ({sym_count} symbols)" if sym_count else ""
        return ProviderCheck("hyperliquid", configured=True, status="healthy", message=f"connected{extra}")

    return ProviderCheck("hyperliquid", configured=True, status="critical", message=f"http {status}")


def _check_allium(*, keystore: Keystore, urlopen: Callable[..., Any]) -> ProviderCheck:
    api_key = _get_optional(keystore, "allium.api_key")
    if not api_key:
        return ProviderCheck("allium", configured=False, status="missing", message="not configured")

    status, payload = _http_json(
        url="https://api.allium.so/api/v1/developer/prices",
        method="POST",
        headers={"x-api-key": api_key},
        body={"inputs": [{"chain": "ethereum", "symbol": "ETH"}]},
        urlopen=urlopen,
    )

    if 200 <= status < 300:
        chains = None
        if isinstance(payload, dict):
            chains = payload.get("chains") or payload.get("supported_chains")
        chain_count = len(chains) if isinstance(chains, list) else None
        if chain_count and chain_count >= 150:
            msg = "150+ chains available"
        elif chain_count:
            msg = f"{chain_count} chains available"
        else:
            msg = "connected"
        return ProviderCheck("allium", configured=True, status="healthy", message=msg)

    if status in {401, 403}:
        return ProviderCheck("allium", configured=True, status="critical", message="unauthorized")
    return ProviderCheck("allium", configured=True, status="critical", message=f"http {status}")


def _check_nansen(*, keystore: Keystore, urlopen: Callable[..., Any]) -> ProviderCheck:
    api_key = _get_optional(keystore, "nansen.api_key")
    if not api_key:
        return ProviderCheck("nansen", configured=False, status="missing", message="not configured")

    status, _payload = _http_json(
        url="https://api.nansen.ai/api/v1/",
        method="GET",
        headers={"apiKey": api_key, "User-Agent": "b1e55ed-cli/keys-test"},
        urlopen=urlopen,
    )
    if 200 <= status < 300:
        return ProviderCheck("nansen", configured=True, status="healthy", message="connected")
    if status in {401, 403}:
        return ProviderCheck("nansen", configured=True, status="critical", message="unauthorized")
    return ProviderCheck("nansen", configured=True, status="critical", message=f"http {status}")


def _check_reddit(*, keystore: Keystore, urlopen: Callable[..., Any]) -> ProviderCheck:
    client_id = _get_optional(keystore, "reddit.client_id")
    if not client_id:
        return ProviderCheck("reddit", configured=False, status="missing", message="not configured")

    params = {
        "client_id": client_id,
        "response_type": "code",
        "state": "b1e55ed",
        "redirect_uri": "http://localhost:8080",
        "duration": "temporary",
        "scope": "read",
    }
    url = "https://www.reddit.com/api/v1/authorize?" + urllib.parse.urlencode(params)
    status, _payload = _http_json(url=url, method="GET", urlopen=urlopen)

    if 200 <= status < 300:
        return ProviderCheck("reddit", configured=True, status="healthy", message="oauth endpoint reachable")
    if status in {400, 404}:
        return ProviderCheck("reddit", configured=True, status="warning", message=f"oauth rejected (http {status})")
    return ProviderCheck("reddit", configured=True, status="critical", message=f"http {status}")


def _check_apify(*, keystore: Keystore, urlopen: Callable[..., Any]) -> ProviderCheck:
    token = _get_optional(keystore, "apify.token")
    if not token:
        return ProviderCheck("apify", configured=False, status="missing", message="not configured")

    url = "https://api.apify.com/v2/users/me?" + urllib.parse.urlencode({"token": token})
    status, payload = _http_json(url=url, method="GET", urlopen=urlopen)

    if 200 <= status < 300:
        username = None
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                username = data.get("username")
        msg = f"authenticated{f' ({username})' if username else ''}"
        return ProviderCheck("apify", configured=True, status="healthy", message=msg)

    if status in {401, 403}:
        return ProviderCheck("apify", configured=True, status="critical", message="unauthorized")

    if status == 429:
        return ProviderCheck("apify", configured=True, status="warning", message="rate limited")

    return ProviderCheck("apify", configured=True, status="critical", message=f"http {status}")


def run_keys_test(
    *,
    keystore: Keystore,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> list[ProviderCheck]:
    return [
        _check_hyperliquid(keystore=keystore, urlopen=urlopen),
        _check_allium(keystore=keystore, urlopen=urlopen),
        _check_nansen(keystore=keystore, urlopen=urlopen),
        _check_reddit(keystore=keystore, urlopen=urlopen),
        _check_apify(keystore=keystore, urlopen=urlopen),
    ]


def cmd_keys_test(*, keystore: Keystore, as_json: bool = False, urlopen: Callable[..., Any] = urllib.request.urlopen) -> int:
    checks = run_keys_test(keystore=keystore, urlopen=urlopen)

    active = sum(1 for c in checks if c.status in {"healthy", "warning"} and c.configured)
    total = len(checks)

    if as_json:
        out = {
            "providers": [
                {
                    "provider": c.provider,
                    "configured": c.configured,
                    "status": c.status,
                    "message": c.message,
                }
                for c in checks
            ],
            "coverage": {
                "active": active,
                "total": total,
                "missing": [c.provider for c in checks if not c.configured],
            },
        }
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0

    max_name = max(len(c.provider) for c in checks) if checks else 10
    for c in checks:
        if not c.configured:
            mark = "❌"
        elif c.status == "healthy":
            mark = "✅"
        elif c.status == "warning":
            mark = "⚠️"
        else:
            mark = "❌"
        print(f"{mark} {c.provider:<{max_name}}  {c.message}")

    print(f"Signal coverage: {active}/{total} providers active")
    return 0
