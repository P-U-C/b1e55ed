"""Cockpit dashboard page — what do I trade today?"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def register(app: FastAPI, templates: Jinja2Templates) -> None:
    @app.get("/cockpit", response_class=HTMLResponse)
    def cockpit_page(request: Request) -> HTMLResponse:
        client = request.app.state.api_client
        res = client.get_cockpit_state()
        state = res.data if (res.ok and isinstance(res.data, dict)) else {}
        ks_num = 0
        sys = state.get("system")
        if isinstance(sys, dict):
            ks_num = sys.get("kill_switch_level_num", 0)
        return templates.TemplateResponse(
            "cockpit.html",
            {
                "request": request,
                "active_page": "cockpit",
                "kill_switch_level": ks_num,
                "regime": "transition",
                "state": state,
            },
        )

    @app.get("/partials/cockpit-content", response_class=HTMLResponse)
    def cockpit_content_partial(request: Request) -> HTMLResponse:
        client = request.app.state.api_client
        res = client.get_cockpit_state()
        state = res.data if (res.ok and isinstance(res.data, dict)) else {}
        return templates.TemplateResponse(
            "partials/cockpit_content.html",
            {"request": request, "state": state},
        )
