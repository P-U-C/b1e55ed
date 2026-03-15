"""engine.mcp.client

MCP client abstraction for consuming external data sources.

Design: Two-layer.
  Layer 1 – MCPClient (abstract): defines the interface any data-source client must satisfy.
  Layer 2 – HttpMCPClient (concrete): implements the interface over plain HTTP/REST.
             Full MCP stdio/SSE protocol support is a follow-up (S2+).

When an MCP server is available for a source, the subclass sets `mcp_source_url` and
overrides `_call_tool()` to use the MCP protocol. Until then, HTTP is the transport.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from typing import Any

import httpx

try:  # pragma: no cover - optional dependency
    from mcp import ClientSession as _MCPClientSession  # type: ignore[import-not-found,import-untyped,unused-ignore]  # optional dep
except ImportError:  # pragma: no cover - optional dependency
    _MCPClientSession = None

MCP_SDK_AVAILABLE = _MCPClientSession is not None


@dataclass(frozen=True, slots=True)
class MCPToolResult:
    """Normalized result from any MCP tool call."""

    tool: str
    data: list[dict]
    source_url: str
    fetched_at: str
    raw: dict


class MCPClient(ABC):
    """Abstract MCP data source client."""

    source_url: str

    @abstractmethod
    def call_tool(self, tool: str, arguments: dict) -> MCPToolResult:
        """Call a tool on the upstream source and return normalized rows."""

    def available(self) -> bool:
        """Return True if the source is reachable. Default: always True."""

        return True


class HttpMCPClient(MCPClient):
    """HTTP/REST adapter.

    Speaks to REST APIs that mirror MCP tool interfaces.
    """

    def __init__(self, base_url: str, api_key: str | None = None, timeout: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.source_url = self.base_url
        self.timeout = timeout
        self.api_key = api_key

        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["X-API-Key"] = api_key
        self._headers = headers

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(tz=UTC).isoformat()

    @staticmethod
    def _normalize_rows(payload: Any) -> list[dict]:
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]

        if isinstance(payload, dict):
            for key in ("data", "results", "rows", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, dict)]
                if isinstance(value, dict):
                    return [value]

            if "error" in payload:
                return []

            return [payload]

        return []

    @staticmethod
    def _response_to_dict(response: httpx.Response) -> dict:
        try:
            body = response.json()
        except ValueError:
            body = {"text": response.text}

        if isinstance(body, dict):
            return body
        if isinstance(body, list):
            return {"data": body}
        return {"value": body}

    def call_tool(self, tool: str, arguments: dict) -> MCPToolResult:
        """Call a mirrored MCP tool over HTTP.

        POSTs to ``{base_url}/tools/{tool}`` with ``arguments`` as JSON body.
        If POST returns 405, falls back to ``GET {base_url}/{tool}`` with query params.

        Never raises: returns an empty ``data`` list on any error.
        """

        tool_name = tool.strip("/")
        args = arguments or {}
        fetched_at = self._now_iso()
        post_url = f"{self.base_url}/tools/{tool_name}"
        get_url = f"{self.base_url}/{tool_name}"

        try:
            with httpx.Client(timeout=self.timeout, headers=self._headers) as client:
                response = client.post(post_url, json=args)
                if response.status_code == 405:
                    response = client.get(get_url, params=args)

                response.raise_for_status()
                raw = self._response_to_dict(response)
                return MCPToolResult(
                    tool=tool_name,
                    data=self._normalize_rows(raw),
                    source_url=self.source_url,
                    fetched_at=fetched_at,
                    raw=raw,
                )
        except Exception as exc:  # noqa: BLE001 - never raise to producer layer
            return MCPToolResult(
                tool=tool_name,
                data=[],
                source_url=self.source_url,
                fetched_at=fetched_at,
                raw={"error": f"{type(exc).__name__}: {exc}"},
            )

    def available(self) -> bool:
        """HEAD request to base URL. Returns False on any error."""

        try:
            with httpx.Client(timeout=self.timeout, headers=self._headers) as client:
                response = client.head(self.base_url)
                response.raise_for_status()
            return True
        except Exception:  # noqa: BLE001
            return False
