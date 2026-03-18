"""Conviction page + partial routes — brain conviction score panels."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def register(app: FastAPI, templates: Jinja2Templates) -> None:
    @app.get("/conviction", response_class=HTMLResponse)
    def conviction_page(request: Request, symbol: str | None = None) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="conviction.html",
            context={
                "request": request,
                "active_page": "conviction",
                "symbol": symbol,
                "convictions": [],
                "conviction_age": "stale",
            },
        )

    @app.get("/partials/conviction", response_class=HTMLResponse)
    def conviction_partial(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="partials/conviction_panel.html",
            context={
                "request": request,
                "convictions": [],
                "conviction_age": "stale",
            },
        )

    @app.get("/partials/conviction-history", response_class=HTMLResponse)
    def conviction_history_partial(request: Request, symbol: str | None = None) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="partials/conviction_panel.html",
            context={
                "request": request,
                "convictions": [],
                "conviction_age": "stale",
                "symbol": symbol,
            },
        )
