from __future__ import annotations

import httpx
import pytest

from engine.core.client import DataClient


@pytest.mark.anyio
async def test_request_json_blocks_too_large(monkeypatch):
    client = DataClient()

    async def _fake_request(method: str, url: str, **kwargs):
        return httpx.Response(200, content=b"x" * (600 * 1024))

    monkeypatch.setattr(client, "request", _fake_request)

    with pytest.raises(httpx.TransportError):
        await client.request_json("GET", "https://example.com", max_bytes=512 * 1024)


@pytest.mark.anyio
async def test_request_json_schema_mismatch(monkeypatch):
    client = DataClient()

    async def _fake_request(method: str, url: str, **kwargs):
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(client, "request", _fake_request)

    with pytest.raises(httpx.TransportError):
        await client.request_json("GET", "https://example.com", expected=list)


@pytest.mark.anyio
async def test_request_json_max_items(monkeypatch):
    client = DataClient()

    async def _fake_request(method: str, url: str, **kwargs):
        return httpx.Response(200, json=[{"i": i} for i in range(10)])

    monkeypatch.setattr(client, "request", _fake_request)

    with pytest.raises(httpx.TransportError):
        await client.request_json("GET", "https://example.com", expected=list, max_items=5)
