"""
Purpose: Serve the simple browser UI for landing page and dashboard.
Input/Output: Renders Jinja templates and passes a few configuration values into the pages.
Invariants: The HTML pages are thin shells; business actions still happen through the JSON API.
Debug: If the dashboard loads but actions fail, compare the rendered page values with the API configuration.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings


router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "is_authenticated": bool(request.session.get("user_id")),
        },
    )


@router.get("/auth", response_class=HTMLResponse)
def auth_page(request: Request) -> HTMLResponse:
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)

    return templates.TemplateResponse(
        "auth.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "demo_mode": settings.demo_mode,
        },
    )


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    if not request.session.get("user_id"):
        return RedirectResponse("/auth", status_code=303)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "demo_mode": settings.demo_mode,
            "smtp_configured": bool(settings.smtp_host),
        },
    )
