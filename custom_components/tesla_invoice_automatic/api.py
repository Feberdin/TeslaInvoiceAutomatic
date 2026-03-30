"""Tesla Fleet API client used by the integration.

Purpose:
    Wrap Tesla HTTP calls, token refresh, and response validation behind a
    small interface that is easy to test and reason about.
Input/Output:
    Accepts Home Assistant config values and returns normalized Python data or
    invoice PDF bytes.
Important invariants:
    Every external request validates required credentials first and raises a
    descriptive error instead of silently continuing with bad state.
How to debug:
    Enable debug logs and inspect the status code plus Tesla response body
    excerpt that gets logged when authentication or invoice download fails.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_API_BASE_URL,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_DOWNLOAD_TIMEOUT_SECONDS,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_URL,
    CONF_VIN,
    DEFAULT_TIMEOUT_SECONDS,
)
from .errors import InvoiceDownloadError, TeslaApiError, TeslaAuthenticationError
from .models import ChargingInvoiceSession, parse_charging_history

_LOGGER = logging.getLogger(__name__)


class TeslaFleetApiClient:
    """Minimal Tesla Fleet API client for charging invoices."""

    def __init__(self, session: ClientSession, config: dict[str, Any]) -> None:
        self._session = session
        self._config = config

    async def async_get_charging_sessions(self) -> list[ChargingInvoiceSession]:
        """Fetch charging history and normalize it."""

        payload = await self._request_json(
            "GET",
            "/api/1/dx/charging/history",
        )
        return parse_charging_history(payload)

    async def async_download_invoice_pdf(self, invoice_id: str) -> bytes:
        """Download one invoice PDF by Tesla invoice ID."""

        if not invoice_id:
            raise InvoiceDownloadError("Tesla invoice ID fehlt. Ohne invoice_id kann kein PDF geladen werden.")

        response = await self._request(
            "GET",
            f"/api/1/dx/charging/invoice/{invoice_id}",
            accept="application/pdf",
        )
        content_type = response.headers.get("Content-Type", "")
        body = await response.read()
        response.release()

        if response.status != 200:
            raise InvoiceDownloadError(
                f"Tesla-Rechnung {invoice_id} konnte nicht geladen werden. "
                f"HTTP-Status: {response.status}. Bitte Tesla-Token, Berechtigungen "
                "und invoice_id pruefen."
            )

        if "pdf" not in content_type.lower():
            raise InvoiceDownloadError(
                f"Tesla lieferte fuer Rechnung {invoice_id} keinen PDF-Inhalt zurueck "
                f"(Content-Type: {content_type or 'unbekannt'})."
            )

        return body

    async def async_refresh_access_token(self) -> str:
        """Refresh the Tesla access token if refresh credentials are available."""

        refresh_token = self._require_config(CONF_REFRESH_TOKEN)
        client_id = self._require_config(CONF_CLIENT_ID)
        client_secret = self._require_config(CONF_CLIENT_SECRET)
        token_url = self._require_config(CONF_TOKEN_URL)

        payload = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }

        try:
            async with self._session.post(token_url, data=payload) as response:
                data = await response.json(content_type=None)
        except ClientError as err:
            raise TeslaAuthenticationError(
                "Tesla OAuth-Token konnte nicht aktualisiert werden. "
                f"Bitte Netzwerk und Token-URL pruefen. Technischer Fehler: {err}"
            ) from err

        if response.status != 200:
            raise TeslaAuthenticationError(
                "Tesla OAuth-Token konnte nicht aktualisiert werden. "
                f"HTTP-Status: {response.status}, Antwort: {str(data)[:300]}"
            )

        access_token = str(data.get("access_token") or "").strip()
        if not access_token:
            raise TeslaAuthenticationError(
                "Tesla OAuth-Antwort enthaelt kein access_token. Bitte client_id, "
                "client_secret und refresh_token pruefen."
            )

        self._config[CONF_ACCESS_TOKEN] = access_token
        if data.get("refresh_token"):
            self._config[CONF_REFRESH_TOKEN] = str(data["refresh_token"])

        _LOGGER.debug("Tesla access token erfolgreich aktualisiert.")
        return access_token

    async def _request_json(self, method: str, path: str) -> dict[str, Any]:
        """Perform one Tesla request and decode JSON with clear errors."""

        response = await self._request(method, path, accept="application/json")
        try:
            payload = await response.json(content_type=None)
        except ValueError as err:
            text = await response.text()
            response.release()
            raise TeslaApiError(
                f"Tesla API lieferte kein gueltiges JSON fuer {path}. "
                f"Antwort-Auszug: {text[:300]}"
            ) from err

        response.release()
        return payload

    async def _request(self, method: str, path: str, accept: str):
        """Send one authorized HTTP request to Tesla, refreshing once on 401."""

        await self._ensure_required_runtime_config()
        response = await self._send(method, path, accept=accept)
        if response.status != 401:
            return response

        response.release()
        _LOGGER.info("Tesla API meldet 401 fuer %s. Versuche Token-Refresh.", path)
        await self.async_refresh_access_token()
        retry_response = await self._send(method, path, accept=accept)
        if retry_response.status == 401:
            text = await retry_response.text()
            retry_response.release()
            raise TeslaAuthenticationError(
                "Tesla API lehnt das Access-Token auch nach einem Refresh ab. "
                f"Pfad: {path}. Antwort-Auszug: {text[:300]}"
            )

        return retry_response

    async def _send(self, method: str, path: str, accept: str):
        """Execute the low-level HTTP request with shared headers and timeout."""

        base_url = self._require_config(CONF_API_BASE_URL).rstrip("/")
        access_token = self._require_config(CONF_ACCESS_TOKEN)
        vin = self._require_config(CONF_VIN)
        timeout_seconds = int(
            self._config.get(CONF_DOWNLOAD_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS)
        )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": accept,
            "X-Tesla-User-Agent": "TeslaInvoiceAutomatic/1.0",
        }

        params = {"vin": vin}
        url = f"{base_url}{path}"

        try:
            return await self._session.request(
                method,
                url,
                headers=headers,
                params=params,
                timeout=timeout_seconds,
            )
        except ClientError as err:
            raise TeslaApiError(
                f"Tesla API konnte nicht erreicht werden: {url}. "
                f"Bitte Netzwerk, Basis-URL und Tesla-Freigaben pruefen. Fehler: {err}"
            ) from err

    async def _ensure_required_runtime_config(self) -> None:
        """Fail fast before the first external request."""

        for key in (
            CONF_API_BASE_URL,
            CONF_ACCESS_TOKEN,
            CONF_VIN,
            CONF_TOKEN_URL,
        ):
            self._require_config(key)

    def _require_config(self, key: str) -> str:
        """Read one required config value or raise a user-friendly error."""

        value = str(self._config.get(key) or "").strip()
        if not value:
            raise TeslaAuthenticationError(
                f"Pflichtfeld '{key}' fehlt in der Tesla-Integration. "
                "Bitte die Konfiguration oeffnen und den Wert hinterlegen."
            )
        return value
