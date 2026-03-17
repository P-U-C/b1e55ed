"""YAML-based adapter spec loader."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class EndpointSpec:
    path: str
    method: str = "GET"
    params: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    timeout_sec: int = 10


@dataclass
class FieldMapping:
    symbol: str  # jsonpath to symbol field
    direction: str  # jsonpath to direction field
    confidence: str  # jsonpath to confidence field
    horizon_hours: str  # jsonpath to horizon OR literal value
    observed_at: str  # jsonpath to timestamp
    # Optional mappings
    regime: str | None = None
    signal_type: str | None = None
    hit_rate: str | None = None
    avg_return: str | None = None
    is_stale: str | None = None
    source_assertion: str | None = None


@dataclass
class AdapterSpec:
    name: str
    version: str
    domain: str
    base_url: str
    signals_endpoint: EndpointSpec
    health_endpoint: EndpointSpec | None
    field_mapping: FieldMapping
    min_confidence: float = 0.55
    stale_threshold_sec: int = 300
    poll_interval_sec: int = 60
    items_path: str = ""  # jsonpath to array of signals in response


def _expand_env(value: str) -> str:
    """Expand ${VAR} references from environment variables."""

    def _replace(match: re.Match[str]) -> str:
        var = match.group(1)
        return os.environ.get(var, match.group(0))

    return re.sub(r"\$\{([^}]+)\}", _replace, value)


def _resolve_env_vars(data: Any) -> Any:
    """Recursively expand ``${VAR}`` and ``${VAR:-default}`` in string values."""
    if isinstance(data, dict):
        return {k: _resolve_env_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_env_vars(item) for item in data]
    if isinstance(data, str):

        def _replace(match: re.Match[str]) -> str:
            expr = match.group(1)
            if ":-" in expr:
                var, default = expr.split(":-", 1)
                return os.getenv(var, default)
            return os.getenv(expr, match.group(0))

        return re.sub(r"\$\{([^}]+)\}", _replace, data)
    return data


def _parse_endpoint(data: dict[str, Any] | None) -> EndpointSpec | None:
    if data is None:
        return None
    return EndpointSpec(
        path=data.get("path", "/"),
        method=data.get("method", "GET"),
        params=data.get("params", {}),
        headers=data.get("headers", {}),
        timeout_sec=int(data.get("timeout_sec", 10)),
    )


def _parse_field_mapping(data: dict[str, Any]) -> FieldMapping:
    return FieldMapping(
        symbol=data["symbol"],
        direction=data["direction"],
        confidence=data["confidence"],
        horizon_hours=str(data["horizon_hours"]),
        observed_at=data["observed_at"],
        regime=data.get("regime"),
        signal_type=data.get("signal_type"),
        hit_rate=data.get("hit_rate"),
        avg_return=data.get("avg_return"),
        is_stale=data.get("is_stale"),
        source_assertion=data.get("source_assertion"),
    )


def load_spec(path: str | Path) -> AdapterSpec:
    """Load and parse an adapter spec from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)

    base_url = _expand_env(str(data["base_url"]))

    # Check for unexpanded placeholders (env vars not set in the environment).
    remaining = re.findall(r"\$\{[^}]+\}", base_url)
    if remaining:
        raise ValueError(
            f"Adapter spec '{data['name']}' has unresolved env var placeholders in base_url: {remaining}. "
            f"Set the required environment variables before starting."
        )

    signals_ep_data = data.get("signals_endpoint")
    if signals_ep_data is None:
        raise ValueError("spec missing required 'signals_endpoint'")

    signals_endpoint = _parse_endpoint(signals_ep_data)
    assert signals_endpoint is not None  # noqa: S101  (invariant — data non-None above)

    health_endpoint = _parse_endpoint(data.get("health_endpoint"))
    field_mapping = _parse_field_mapping(data["field_mapping"])

    return AdapterSpec(
        name=data["name"],
        version=str(data["version"]),
        domain=data["domain"],
        base_url=base_url,
        signals_endpoint=signals_endpoint,
        health_endpoint=health_endpoint,
        field_mapping=field_mapping,
        min_confidence=float(data.get("min_confidence", 0.55)),
        stale_threshold_sec=int(data.get("stale_threshold_sec", 300)),
        poll_interval_sec=int(data.get("poll_interval_sec", 60)),
        items_path=str(data.get("items_path", "")),
    )


def load_spec_inline(data: dict) -> AdapterSpec:
    """Load an AdapterSpec from an inline dict (no file I/O — works in binary installs)."""
    # Resolve env vars in string values (same as load_spec does).
    data = _resolve_env_vars(data)

    signals_ep_data = data.get("signals_endpoint")
    if signals_ep_data is None:
        raise ValueError("spec missing required 'signals_endpoint'")

    signals_endpoint = _parse_endpoint(signals_ep_data)
    assert signals_endpoint is not None  # noqa: S101

    health_endpoint = _parse_endpoint(data.get("health_endpoint"))
    field_mapping = _parse_field_mapping(data["field_mapping"])

    return AdapterSpec(
        name=data["name"],
        version=str(data["version"]),
        domain=data["domain"],
        base_url=str(data["base_url"]),
        signals_endpoint=signals_endpoint,
        health_endpoint=health_endpoint,
        field_mapping=field_mapping,
        min_confidence=float(data.get("min_confidence", 0.55)),
        stale_threshold_sec=int(data.get("stale_threshold_sec", 300)),
        poll_interval_sec=int(data.get("poll_interval_sec", 60)),
        items_path=str(data.get("items_path", "")),
    )
