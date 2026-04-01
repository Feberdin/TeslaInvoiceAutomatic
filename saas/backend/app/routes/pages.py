"""
Purpose: Serve the simple browser UI for landing page and dashboard.
Input/Output: Renders Jinja templates and passes a few configuration values into the pages.
Invariants: The HTML pages are thin shells; business actions still happen through the JSON API.
Debug: If the dashboard loads but actions fail, compare the rendered page values with the API configuration.
"""

from __future__ import annotations

from sqlalchemy import select

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.admin import user_is_admin
from app.config import get_settings
from app.database import get_db_session
from app.models import User
from app.services.tesla_partner import TeslaPartnerAdminService


router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
partner_admin_service = TeslaPartnerAdminService(settings)


def _template_context(request: Request, db: Session) -> dict[str, object]:
    """Build the common template context including auth and admin navigation state."""

    user_id = request.session.get("user_id")
    is_authenticated = isinstance(user_id, int)
    user = db.scalar(select(User).where(User.id == user_id)) if is_authenticated else None
    is_admin = user_is_admin(settings, user.email if user else None)
    return {
        "request": request,
        "app_name": settings.app_name,
        "is_authenticated": is_authenticated,
        "is_admin": is_admin,
        "admin_path": "/admin" if is_admin else None,
        "current_user_email": user.email if user else None,
    }


@router.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db_session)) -> HTMLResponse:
    context = _template_context(request, db)
    return templates.TemplateResponse(
        "index.html",
        {
            **context,
        },
    )


@router.get("/auth", response_class=HTMLResponse)
def auth_page(request: Request, db: Session = Depends(get_db_session)) -> HTMLResponse:
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)

    context = _template_context(request, db)
    return templates.TemplateResponse(
        "auth.html",
        {
            **context,
            "demo_mode": settings.demo_mode,
        },
    )


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db_session)) -> HTMLResponse:
    if not request.session.get("user_id"):
        return RedirectResponse("/auth", status_code=303)

    context = _template_context(request, db)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            **context,
            "demo_mode": settings.demo_mode,
            "smtp_configured": bool(settings.smtp_host),
        },
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(get_db_session)) -> HTMLResponse:
    if not request.session.get("user_id"):
        return RedirectResponse("/auth", status_code=303)

    context = _template_context(request, db)
    if not context["is_admin"]:
        raise HTTPException(
            status_code=403,
            detail="Dieses Admin-Menue ist nur fuer Betreiber freigeschaltet. Bitte `ADMIN_EMAILS` pruefen.",
        )

    return templates.TemplateResponse(
        "admin.html",
        {
            **context,
        },
    )


@router.api_route(
    "/.well-known/appspecific/com.tesla.3p.public-key.pem",
    methods=["GET", "HEAD"],
    response_class=PlainTextResponse,
)
def tesla_public_key() -> PlainTextResponse:
    public_key_pem = partner_admin_service.public_key_pem()
    if not public_key_pem:
        raise HTTPException(
            status_code=404,
            detail=(
                "Der Tesla-Fleet-Public-Key wurde noch nicht erzeugt. "
                "Bitte zuerst das Admin-Menue in der App verwenden."
            ),
        )
    return PlainTextResponse(public_key_pem, media_type="application/x-pem-file")
