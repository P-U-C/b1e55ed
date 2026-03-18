"""Cockpit dashboard page — merged into Brain.

Cockpit content is now part of the Brain page. This route redirects.
The partial endpoint is kept for any existing HTMX polling.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates


def register(app: FastAPI, templates: Jinja2Templates) -> None:
    @app.get("/cockpit", response_class=RedirectResponse)
    def cockpit_page(request: Request) -> RedirectResponse:
        return RedirectResponse(url="/", status_code=302)

    @app.get("/partials/cockpit-content", response_class=HTMLResponse)
    def cockpit_content_partial(request: Request) -> HTMLResponse:
        """Kept for backward compat — existing HTMX polls may hit this."""
        client = request.app.state.api_client
        res = client.get_cockpit_state()
        state = res.data if (res.ok and isinstance(res.data, dict)) else {}
        return templates.TemplateResponse(
            request=request,
            name="partials/cockpit_content.html",
            context={"request": request, "state": state},
        )
