from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI


def make_client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")
