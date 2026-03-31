"""
Purpose: Run the recurring background sync loop outside the web request cycle.
Input/Output: Periodically reads all connected users from the DB and triggers invoice synchronization.
Invariants: Each loop uses a fresh DB session, logs its outcome and sleeps for the configured interval.
Debug: If automatic sync does not run, start by checking the worker container logs and the sleep interval here.
"""

from __future__ import annotations

import logging
import time
from threading import Event

from app.config import get_settings
from app.database import SessionLocal, create_database
from app.logging_config import configure_logging
from app.services.emailer import ConsoleEmailService
from app.services.storage import LocalFileStorage
from app.services.sync import InvoiceSyncService, RuntimeServices
from app.services.tesla import DemoTeslaClient


settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


def run_worker_cycle() -> int:
    session = SessionLocal()
    try:
        runtime_services = RuntimeServices(
            tesla_client=DemoTeslaClient(),
            storage=LocalFileStorage(settings.data_dir),
            emailer=ConsoleEmailService(settings.data_dir, settings.default_from_email),
        )
        sync_service = InvoiceSyncService(session, runtime_services)
        summaries = sync_service.sync_all_users()
        logger.info("Worker cycle finished. synced_users=%s", len(summaries))
        return len(summaries)
    except Exception:
        logger.exception("Worker cycle failed. Bitte Logs pruefen und Datenbank/Volumes kontrollieren.")
        session.rollback()
        return 0
    finally:
        session.close()


def run_worker_loop(stop_event: Event | None = None) -> None:
    create_database()
    logger.info("Worker started with interval=%s seconds", settings.sync_interval_seconds)

    while stop_event is None or not stop_event.is_set():
        run_worker_cycle()

        if stop_event is None:
            time.sleep(settings.sync_interval_seconds)
            continue

        # Sleeping in short intervals makes container shutdown on Unraid much more responsive.
        if stop_event.wait(timeout=settings.sync_interval_seconds):
            break


if __name__ == "__main__":
    run_worker_loop()
