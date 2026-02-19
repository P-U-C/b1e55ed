from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def make_client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")
