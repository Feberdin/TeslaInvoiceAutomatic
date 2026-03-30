"""Coordinator that scans a PDF folder and emails new files.

Purpose:
    Centralize the integration workflow so Home Assistant watches one local
    folder and reliably emails newly added Tesla PDF files.
Input/Output:
    Reads config-entry data, scans the configured watch directory, updates
    persisted state, and exposes a summary object for entities and diagnostics.
Important invariants:
    A file is only marked as processed after its bytes were read and the email
    was sent successfully.
How to debug:
    Start with the coordinator logs, then compare the watch directory contents
    with the stored processed file IDs.
"""

from __future__ import annotations

import fnmatch
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LocalInvoicePdfClient
from .const import (
    CONF_FILE_PATTERN,
    CONF_POLL_INTERVAL_MINUTES,
    CONF_WATCH_DIRECTORY,
    COORDINATOR_NAME,
    DEFAULT_HISTORY_MAX_INVOICES,
    DEFAULT_POLL_INTERVAL_MINUTES,
)
from .emailer import send_invoice_email
from .errors import EmailDeliveryError, InvoiceDownloadError, TeslaInvoiceAutomaticError
from .models import ProcessingResult, filter_files_by_age, select_pending_files
from .store import IntegrationState, TeslaInvoiceStore

_LOGGER = logging.getLogger(__name__)


class TeslaInvoiceCoordinator(DataUpdateCoordinator[ProcessingResult]):
    """Polling coordinator for the local PDF workflow."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: TeslaInvoiceStore,
    ) -> None:
        update_interval_seconds = int(
            entry.options.get(
                CONF_POLL_INTERVAL_MINUTES,
                entry.data.get(CONF_POLL_INTERVAL_MINUTES, DEFAULT_POLL_INTERVAL_MINUTES),
            )
        ) * 60
        super().__init__(
            hass,
            _LOGGER,
            name=COORDINATOR_NAME,
            update_interval=timedelta(seconds=update_interval_seconds),
        )
        self.config_entry = entry
        self._store = store
        self._client = LocalInvoicePdfClient()
        self._state = IntegrationState()
        self.data = ProcessingResult([], None, None, None, None, None, 0)

    @property
    def runtime_config(self) -> dict:
        """Merge config-entry data and options into one runtime mapping."""

        return {**self.config_entry.data, **self.config_entry.options}

    async def async_initialize(self) -> None:
        """Load persisted state before the first refresh."""

        self._state = await self._store.async_load()
        self.data = self._build_result(0)

    async def _async_update_data(self) -> ProcessingResult:
        """Poll the watch directory for new PDFs and process them."""

        try:
            return await self._async_process_files(
                days_back=0,
                max_invoices=DEFAULT_HISTORY_MAX_INVOICES,
                include_processed=False,
            )
        except (InvoiceDownloadError, EmailDeliveryError, TeslaInvoiceAutomaticError) as err:
            self._state.last_error = str(err)
            await self._store.async_save(self._state)
            raise UpdateFailed(str(err)) from err

    async def async_send_latest_invoice_now(self) -> None:
        """Manually trigger one immediate refresh."""

        await self.async_request_refresh()

    async def async_send_historical_invoices(
        self,
        *,
        days_back: int,
        max_invoices: int,
        include_processed: bool,
    ) -> ProcessingResult:
        """Process older local PDFs on demand."""

        result = await self._async_process_files(
            days_back=days_back,
            max_invoices=max_invoices,
            include_processed=include_processed,
        )
        self.async_set_updated_data(result)
        return result

    async def _async_process_files(
        self,
        *,
        days_back: int,
        max_invoices: int,
        include_processed: bool,
    ) -> ProcessingResult:
        """Scan the watch directory, filter files, and send matching PDFs."""

        files = await self.hass.async_add_executor_job(self._list_matching_files)
        candidate_files = filter_files_by_age(files, days_back=days_back)
        if not include_processed:
            candidate_files = select_pending_files(
                candidate_files,
                set(self._state.processed_invoice_ids),
            )

        files_to_process = list(reversed(candidate_files[:max_invoices]))
        for invoice_file in files_to_process:
            pdf_content = await self.hass.async_add_executor_job(
                self._client.read_invoice_pdf,
                invoice_file.file_path,
            )
            await self.hass.async_add_executor_job(
                send_invoice_email,
                self.runtime_config,
                invoice_file,
                pdf_content,
                invoice_file.file_path,
            )
            if invoice_file.file_id not in self._state.processed_invoice_ids:
                self._state.processed_invoice_ids.append(invoice_file.file_id)
            self._state.last_invoice_id = invoice_file.file_id
            self._state.last_session_id = invoice_file.file_name
            self._state.last_downloaded_file = str(invoice_file.file_path)
            self._state.last_email_at = datetime.now(timezone.utc).isoformat()
            self._state.last_error = None
            if days_back > 0:
                self._state.last_history_import_at = self._state.last_email_at
                self._state.last_history_days = days_back
            await self._store.async_save(self._state)
            _LOGGER.info(
                "PDF-Rechnung %s erfolgreich per E-Mail versendet.",
                invoice_file.file_name,
            )

        return self._build_result(len(candidate_files))

    def _list_matching_files(self):
        """Read and filter PDF files from the configured watch directory."""

        watch_directory = Path(str(self.runtime_config[CONF_WATCH_DIRECTORY]).strip())
        file_pattern = str(self.runtime_config.get(CONF_FILE_PATTERN, "*.pdf") or "*.pdf").strip()
        files = self._client.list_invoice_files(watch_directory)
        return [item for item in files if fnmatch.fnmatch(item.file_name, file_pattern)]

    def _build_result(self, pending_invoice_count: int) -> ProcessingResult:
        """Build the entity-facing coordinator result."""

        return ProcessingResult(
            processed_invoice_ids=list(dict.fromkeys(self._state.processed_invoice_ids)),
            last_invoice_id=self._state.last_invoice_id,
            last_session_id=self._state.last_session_id,
            last_downloaded_file=self._state.last_downloaded_file,
            last_email_at=self._state.last_email_at,
            last_error=self._state.last_error,
            pending_invoice_count=pending_invoice_count,
            last_history_import_at=self._state.last_history_import_at,
            last_history_days=self._state.last_history_days,
        )
