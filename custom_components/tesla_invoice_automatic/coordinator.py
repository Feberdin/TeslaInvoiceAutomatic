"""Coordinator that downloads Tesla invoice PDFs and emails them.

Purpose:
    Centralize the workflow so Home Assistant can poll Tesla charging history,
    download official Tesla PDF invoices, store them locally, and email new
    ones.
Input/Output:
    Reads config-entry data, talks to Tesla ownership endpoints + SMTP, updates
    persisted state, and exposes a summary object for entities and diagnostics.
Important invariants:
    An invoice is only marked as processed after both PDF save and email send
    succeed. This prevents false positives after partial failures.
How to debug:
    Start with the coordinator logs. They show whether the failure happened
    during history fetch, PDF download, local save, or SMTP delivery.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TeslaOwnershipInvoiceClient
from .const import (
    CONF_POLL_INTERVAL_MINUTES,
    COORDINATOR_NAME,
    DEFAULT_HISTORY_MAX_INVOICES,
    DEFAULT_POLL_INTERVAL_MINUTES,
    DOMAIN,
    INVOICE_DIRECTORY_NAME,
    RUN_STATUS_ERROR,
    RUN_STATUS_IDLE,
    RUN_STATUS_NO_NEW_INVOICES,
    RUN_STATUS_SENT,
)
from .emailer import send_invoice_email
from .errors import (
    EmailDeliveryError,
    InvoiceDownloadError,
    TeslaApiError,
    TeslaAuthenticationError,
    TeslaInvoiceAutomaticError,
)
from .models import (
    ProcessingResult,
    build_invoice_file_path,
    current_month_key,
    filter_invoices_by_age,
    normalize_monthly_invoice_count,
    select_pending_invoices,
)
from .store import IntegrationState, TeslaInvoiceStore

_LOGGER = logging.getLogger(__name__)


class TeslaInvoiceCoordinator(DataUpdateCoordinator[ProcessingResult]):
    """Polling coordinator for the Tesla invoice workflow."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        session: ClientSession,
        store: TeslaInvoiceStore,
        email: str,
        cache_file: Path,
        linked_title: str,
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
        self._linked_title = linked_title
        self._api = TeslaOwnershipInvoiceClient(
            session,
            email=email,
            cache_file=cache_file,
            config=self.runtime_config,
        )
        self._state = IntegrationState()
        self.data = ProcessingResult(
            processed_invoice_ids=[],
            last_invoice_id=None,
            last_session_id=None,
            last_downloaded_file=None,
            last_email_at=None,
            last_error=None,
            pending_invoice_count=0,
            last_run_status=RUN_STATUS_IDLE,
        )

    @property
    def runtime_config(self) -> dict[str, Any]:
        """Merge config-entry data and options into one mutable runtime mapping."""

        return {**self.config_entry.data, **self.config_entry.options}

    @property
    def linked_title(self) -> str:
        """Return the linked tesla_ha label for entities and diagnostics."""

        return self._linked_title

    async def async_initialize(self) -> None:
        """Load persisted state before the first refresh."""

        self._state = await self._store.async_load()
        self._normalize_monthly_counters()
        self.data = self._build_result(0)

    async def _async_update_data(self) -> ProcessingResult:
        """Poll Tesla for new invoices and process pending items."""

        try:
            return await self._async_process_invoices(
                days_back=0,
                max_invoices=DEFAULT_HISTORY_MAX_INVOICES,
                include_processed=False,
            )
        except (
            TeslaApiError,
            TeslaAuthenticationError,
            InvoiceDownloadError,
            EmailDeliveryError,
            TeslaInvoiceAutomaticError,
        ) as err:
            raise UpdateFailed(str(err)) from err

    async def async_send_latest_invoice_now(self) -> None:
        """Manually trigger one immediate coordinator refresh."""

        await self.async_request_refresh()

    async def async_send_historical_invoices(
        self,
        *,
        days_back: int,
        max_invoices: int,
        include_processed: bool,
    ) -> ProcessingResult:
        """Process older invoices on demand."""

        result = await self._async_process_invoices(
            days_back=days_back,
            max_invoices=max_invoices,
            include_processed=include_processed,
        )
        self.async_set_updated_data(result)
        return result

    async def _async_process_invoices(
        self,
        *,
        days_back: int,
        max_invoices: int,
        include_processed: bool,
    ) -> ProcessingResult:
        """Fetch Tesla sessions, filter them, and send matching invoices."""

        started_at = datetime.now(timezone.utc)
        processed_count = 0
        self._state.last_fetch_attempt_at = started_at.isoformat()
        self._normalize_monthly_counters(reference=started_at)

        try:
            invoices = await self._api.async_get_charging_invoices()
            candidate_invoices = filter_invoices_by_age(invoices, days_back=days_back)
            if not include_processed:
                candidate_invoices = select_pending_invoices(
                    candidate_invoices,
                    set(self._state.processed_invoice_ids),
                )

            invoices_to_process = list(reversed(candidate_invoices[:max_invoices]))
            for invoice in invoices_to_process:
                pdf_content = await self._api.async_download_invoice_pdf(invoice.content_id)
                pdf_path = await self._async_save_invoice_file(invoice, pdf_content)
                await self.hass.async_add_executor_job(
                    send_invoice_email,
                    self.runtime_config,
                    invoice,
                    pdf_content,
                    pdf_path,
                )
                sent_at = datetime.now(timezone.utc)
                self._record_successful_invoice_delivery(invoice, pdf_path, sent_at)
                processed_count += 1
                if days_back > 0:
                    self._state.last_history_import_at = sent_at.isoformat()
                    self._state.last_history_days = days_back
                await self._store.async_save(self._state)
                _LOGGER.info(
                    "Tesla-Rechnung %s erfolgreich verarbeitet und gespeichert unter %s.",
                    invoice.content_id,
                    pdf_path,
                )

            completed_at = datetime.now(timezone.utc)
            remaining_invoice_count = max(
                len(candidate_invoices) - len(invoices_to_process),
                0,
            )
            self._record_successful_run(
                started_at=started_at,
                completed_at=completed_at,
                processed_count=processed_count,
                days_back=days_back,
            )
            await self._store.async_save(self._state)
            return self._build_result(remaining_invoice_count)
        except (
            TeslaApiError,
            TeslaAuthenticationError,
            InvoiceDownloadError,
            EmailDeliveryError,
            TeslaInvoiceAutomaticError,
        ) as err:
            self._record_failed_run(
                error=err,
                started_at=started_at,
                failed_at=datetime.now(timezone.utc),
                processed_count=processed_count,
            )
            await self._store.async_save(self._state)
            raise

    async def _async_save_invoice_file(self, invoice, pdf_content: bytes) -> Path:
        """Persist the downloaded PDF under the Home Assistant config directory."""

        invoice_dir = Path(self.hass.config.path(DOMAIN, INVOICE_DIRECTORY_NAME))
        await self.hass.async_add_executor_job(
            lambda: invoice_dir.mkdir(parents=True, exist_ok=True)
        )
        pdf_path = build_invoice_file_path(invoice_dir, invoice)
        await self.hass.async_add_executor_job(pdf_path.write_bytes, pdf_content)
        return pdf_path

    def _build_result(self, pending_invoice_count: int) -> ProcessingResult:
        """Build the entity-facing coordinator result."""

        self._normalize_monthly_counters()
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
            last_fetch_attempt_at=self._state.last_fetch_attempt_at,
            last_successful_fetch_at=self._state.last_successful_fetch_at,
            last_fetch_duration_seconds=self._state.last_fetch_duration_seconds,
            last_run_status=self._state.last_run_status or RUN_STATUS_IDLE,
            last_run_processed_count=self._state.last_run_processed_count,
            invoices_sent_total=self._state.invoices_sent_total,
            invoices_sent_this_month=self._state.invoices_sent_this_month,
            consecutive_failures=self._state.consecutive_failures,
        )

    def _record_successful_invoice_delivery(
        self,
        invoice,
        pdf_path: Path,
        sent_at: datetime,
    ) -> None:
        """Update invoice-specific counters only after email delivery succeeded."""

        sent_at_iso = sent_at.isoformat()
        if invoice.content_id not in self._state.processed_invoice_ids:
            self._state.processed_invoice_ids.append(invoice.content_id)
        self._state.last_invoice_id = invoice.content_id
        self._state.last_session_id = invoice.session_id or invoice.file_name
        self._state.last_downloaded_file = str(pdf_path)
        self._state.last_email_at = sent_at_iso
        self._state.invoices_sent_total += 1
        self._normalize_monthly_counters(reference=sent_at)
        self._state.invoices_sent_this_month += 1

    def _record_successful_run(
        self,
        *,
        started_at: datetime,
        completed_at: datetime,
        processed_count: int,
        days_back: int,
    ) -> None:
        """Persist summary fields for a successful fetch/process cycle."""

        completed_at_iso = completed_at.isoformat()
        self._state.last_successful_fetch_at = completed_at_iso
        self._state.last_fetch_duration_seconds = round(
            (completed_at - started_at).total_seconds(),
            3,
        )
        self._state.last_run_status = (
            RUN_STATUS_SENT if processed_count > 0 else RUN_STATUS_NO_NEW_INVOICES
        )
        self._state.last_run_processed_count = processed_count
        self._state.consecutive_failures = 0
        self._state.last_error = None
        if days_back > 0:
            self._state.last_history_import_at = completed_at_iso
            self._state.last_history_days = days_back

    def _record_failed_run(
        self,
        *,
        error: Exception,
        started_at: datetime,
        failed_at: datetime,
        processed_count: int,
    ) -> None:
        """Persist summary fields for a failed fetch/process cycle."""

        self._state.last_fetch_duration_seconds = round(
            (failed_at - started_at).total_seconds(),
            3,
        )
        self._state.last_run_status = RUN_STATUS_ERROR
        self._state.last_run_processed_count = processed_count
        self._state.consecutive_failures += 1
        self._state.last_error = str(error)

    def _normalize_monthly_counters(self, reference: datetime | None = None) -> None:
        """Reset month-local counters automatically when a new month begins."""

        month_key, count = normalize_monthly_invoice_count(
            self._state.invoices_sent_this_month_key,
            self._state.invoices_sent_this_month,
            reference=reference,
        )
        self._state.invoices_sent_this_month_key = month_key or current_month_key(reference)
        self._state.invoices_sent_this_month = count
