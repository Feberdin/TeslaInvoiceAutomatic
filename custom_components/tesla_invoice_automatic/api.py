"""Tesla API client that reuses the free tesla-ha login cache.

Purpose:
    Authenticate through the already configured `tesla_ha` integration so this
    project does not require Fleet API client credentials from the operator.
Input/Output:
    Uses the linked Tesla e-mail plus TeslaPy cache file and returns normalized
    charging-history data or raw PDF bytes.
Important invariants:
    The linked `tesla_ha` entry must still be logged in with Tesla. Requests are
    synchronous because TeslaPy is request-session based and run in an executor.
How to debug:
    If Tesla authentication fails, first re-open the `tesla_ha` integration and
    complete the Tesla login there. This integration depends on the same cache.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import teslapy

from .const import CONF_API_BASE_URL, CONF_DOWNLOAD_TIMEOUT_SECONDS, CONF_VIN, DEFAULT_TIMEOUT_SECONDS
from .errors import InvoiceDownloadError, TeslaApiError, TeslaAuthenticationError
from .models import ChargingInvoiceSession, parse_charging_history


class TeslaApiClient:
    """Tesla client using the shared TeslaPy cache from tesla-ha."""

    def __init__(self, email: str, cache_file: Path, config: dict[str, Any]) -> None:
        self._email = email
        self._cache_file = cache_file
        self._config = config

    def get_charging_sessions(self) -> list[ChargingInvoiceSession]:
        """Fetch charging history and normalize it."""

        payload = self._request_json("GET", "/api/1/dx/charging/history")
        return parse_charging_history(payload)

    def download_invoice_pdf(self, invoice_id: str) -> bytes:
        """Download one invoice PDF by Tesla invoice ID."""

        if not invoice_id:
            raise InvoiceDownloadError("Tesla invoice ID fehlt. Ohne invoice_id kann kein PDF geladen werden.")

        response = self._request(
            "GET",
            f"/api/1/dx/charging/invoice/{invoice_id}",
            accept="application/pdf",
        )
        content_type = response.headers.get("Content-Type", "")
        body = response.content

        if response.status_code != 200:
            raise InvoiceDownloadError(
                f"Tesla-Rechnung {invoice_id} konnte nicht geladen werden. "
                f"HTTP-Status: {response.status_code}. Bitte pruefen, ob `tesla_ha` "
                "noch korrekt angemeldet ist und Tesla fuer diese Session eine "
                "Rechnung bereitstellt."
            )

        if "pdf" not in content_type.lower():
            raise InvoiceDownloadError(
                f"Tesla lieferte fuer Rechnung {invoice_id} keinen PDF-Inhalt zurueck "
                f"(Content-Type: {content_type or 'unbekannt'})."
            )

        return body

    def _request_json(self, method: str, path: str) -> dict[str, Any]:
        """Perform one Tesla request and decode JSON with clear errors."""

        response = self._request(method, path, accept="application/json")
        try:
            return response.json()
        except ValueError as err:
            raise TeslaApiError(
                f"Tesla API lieferte kein gueltiges JSON fuer {path}. "
                f"Antwort-Auszug: {response.text[:300]}"
            ) from err

    def _request(self, method: str, path: str, accept: str):
        """Execute one low-level HTTP request using TeslaPy's session."""

        base_url = self._require_config(CONF_API_BASE_URL).rstrip("/")
        vin = self._require_config(CONF_VIN)
        timeout_seconds = int(
            self._config.get(CONF_DOWNLOAD_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS)
        )
        url = f"{base_url}{path}"

        headers = {
            "Accept": accept,
            "X-Tesla-User-Agent": "TeslaInvoiceAutomatic/1.0",
        }
        params = {"vin": vin}

        if not self._cache_file.exists():
            raise TeslaAuthenticationError(
                "Die gemeinsame Tesla-Anmeldung wurde nicht gefunden. Bitte zuerst "
                "die `tesla_ha` Integration einrichten oder dort erneut anmelden."
            )

        try:
            with teslapy.Tesla(
                self._email,
                cache_file=str(self._cache_file),
                timeout=timeout_seconds,
                user_agent="TeslaInvoiceAutomatic/1.0",
            ) as tesla:
                if not tesla.authorized:
                    raise TeslaAuthenticationError(
                        "Die verknuepfte `tesla_ha` Integration ist nicht mehr bei "
                        "Tesla angemeldet. Bitte dort den Login erneuern."
                    )

                return tesla.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    serialize=False,
                    timeout=timeout_seconds,
                )
        except TeslaAuthenticationError:
            raise
        except Exception as err:
            raise TeslaApiError(
                f"Tesla API konnte nicht erreicht werden: {url}. "
                f"Bitte `tesla_ha`, Netzwerk und Tesla-Zugang pruefen. Fehler: {err}"
            ) from err

    def _require_config(self, key: str) -> str:
        """Read one required config value or raise a user-friendly error."""

        value = str(self._config.get(key) or "").strip()
        if not value:
            raise TeslaAuthenticationError(
                f"Pflichtfeld '{key}' fehlt in der Tesla-Integration. "
                "Bitte die Konfiguration oeffnen und den Wert hinterlegen."
            )
        return value
