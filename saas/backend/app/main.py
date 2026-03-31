"""
Purpose: Create the FastAPI application, wire routers, static assets and startup initialization.
Input/Output: Starts the web server that serves both the UI and the JSON API.
Invariants: Database tables and data directories are created before requests are handled.
Debug: If the app starts but behaves strangely, inspect the startup logs for schema or path initialization issues.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import create_database
from app.logging_config import configure_logging
from app.routes.api import router as api_router
from app.routes.pages import router as pages_router


settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(api_router)
app.include_router(pages_router)


@app.on_event("startup")
def startup() -> None:
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    create_database()

