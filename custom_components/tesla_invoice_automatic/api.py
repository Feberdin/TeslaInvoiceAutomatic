"""Tesla ownership charging client for official invoice PDF downloads.

Purpose:
    Reuse the login cache of the existing `tesla_ha` integration and call the
    same ownership/mobile charging endpoints that Tesla's apps use for invoice
    history and PDF downloads.
Input/Output:
    Reads the linked TeslaPy cache file, refreshes tokens when needed, and
    returns charging history JSON or PDF bytes.
Important invariants:
    The linked `tesla_ha` cache must contain a valid Tesla owner `sso` token.
    Requests target Tesla's mobile-app ownership endpoints rather than the paid
    Fleet API.
How to debug:
    If requests fail, inspect the cached token freshness, the linked `tesla_ha`
    entry, and the exact ownership endpoint/status code in the logs.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

import aiohttp

from .const import (
    CONF_DEVICE_COUNTRY,
    CONF_DEVICE_LANGUAGE,
    CONF_HTTP_LOCALE,
    CONF_OWNERSHIP_BASE_URL,
    CONF_VIN,
    DEFAULT_DEVICE_COUNTRY,
    DEFAULT_DEVICE_LANGUAGE,
    DEFAULT_HTTP_LOCALE,
    DEFAULT_OWNERSHIP_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    FALLBACK_OWNERSHIP_BASE_URLS,
)
from .errors import InvoiceDownloadError, TeslaApiError, TeslaAuthenticationError
from .models import ChargingInvoiceDocument, parse_charging_history


class TeslaOwnershipInvoiceClient:
    """Client for Tesla ownership charging history and invoice PDFs."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        email: str,
        cache_file: Path,
        config: dict[str, Any],
    ) -> None:
        self._session = session
        self._email = email
        self._cache_file = cache_file
        self._config = config

    async def async_get_charging_invoices(self) -> list[ChargingInvoiceDocument]:
        """Fetch charging history and normalize all downloadable invoices."""

        response = await self._request_json(
            "history",
            params=self._build_history_query_params(),
        )
        return parse_charging_history(response)

    async def async_download_invoice_pdf(self, content_id: str) -> bytes:
        """Download one invoice PDF from Tesla's ownership mobile endpoint."""

        if not content_id:
            raise InvoiceDownloadError("Tesla contentId fehlt. Ohne contentId kann kein PDF geladen werden.")

        return await self._request_bytes(
            f"invoice/{content_id}",
            params=self._build_invoice_query_params(),
        )

    async def _request_json(
        self,
        path_suffix: str,
        *,
        params: dict[str, str],
    ) -> dict[str, Any]:
        """Perform one JSON request with automatic token refresh on 401."""

        response = await self._request(
            "GET",
            path_suffix,
            expect_pdf=False,
            params=params,
        )
        status = response.status
        try:
            payload = await response.json(content_type=None)
        except ValueError as err:
            text = await response.text()
            raise TeslaApiError(
                f"Tesla Ownership API lieferte kein gueltiges JSON fuer {path_suffix}. "
                f"Antwort-Auszug: {text[:300]}"
            ) from err
        finally:
            response.release()

        if status >= 400:
            raise TeslaApiError(
                "Tesla Ownership API lieferte einen Fehler fuer "
                f"{path_suffix}. HTTP-Status: {status}. Antwort: {self._short_payload(payload)}"
            )
        return payload

    async def _request_bytes(
        self,
        path_suffix: str,
        *,
        params: dict[str, str],
    ) -> bytes:
        """Perform one PDF request with automatic token refresh on 401."""

        response = await self._request(
            "GET",
            path_suffix,
            expect_pdf=True,
            params=params,
        )
        content_type = response.headers.get("Content-Type", "")
        data = await response.read()
        response.release()

        if response.status != 200:
            raise InvoiceDownloadError(
                f"Tesla-Rechnung {path_suffix} konnte nicht geladen werden. "
                f"HTTP-Status: {response.status}. Antwort-Auszug: {data[:200]!r}"
            )
        if "pdf" not in content_type.lower() and not data.startswith(b"%PDF"):
            raise InvoiceDownloadError(
                f"Tesla lieferte fuer {path_suffix} keinen PDF-Inhalt zurueck "
                f"(Content-Type: {content_type or 'unbekannt'})."
            )
        return data

    async def _request(
        self,
        method: str,
        path_suffix: str,
        *,
        expect_pdf: bool,
        params: dict[str, str],
    ):
        """Send one ownership request and retry once after token refresh."""

        access_token, _ = await self._async_get_valid_tokens()
        last_fallback_error: str | None = None

        # Tesla verwendet mehrere mobile-app Pfadvarianten. Die konfigurierte
        # URL gewinnt, aber bei klaren Pfadfehlern probieren wir bekannte
        # Alternativen, damit die Integration auch nach Tesla-Routingsaendern
        # robuster bleibt.
        for base_url in self._candidate_base_urls():
            response = await self._send(
                method,
                base_url=base_url,
                path_suffix=path_suffix,
                access_token=access_token,
                params=params,
                expect_pdf=expect_pdf,
            )
            if response.status == 401:
                response.release()
                access_token, _ = await self._async_refresh_tokens()
                response = await self._send(
                    method,
                    base_url=base_url,
                    path_suffix=path_suffix,
                    access_token=access_token,
                    params=params,
                    expect_pdf=expect_pdf,
                )
                if response.status == 401:
                    text = await response.text()
                    response.release()
                    raise TeslaAuthenticationError(
                        "Tesla lehnt das Owner-Token auch nach Refresh ab. "
                        f"Pfad: {path_suffix}, Basis-URL: {base_url}. "
                        f"Antwort-Auszug: {text[:300]}"
                    )

            if response.status not in (404, 405):
                return response

            text = await response.text()
            response.release()
            last_fallback_error = (
                f"Pfad {path_suffix} unter {base_url} antwortete mit HTTP "
                f"{response.status}: {text[:200]}"
            )

        raise TeslaApiError(
            "Tesla Ownership API konnte keinen funktionierenden Endpunkt fuer "
            f"{path_suffix} finden. Letzter Fehler: {last_fallback_error or 'unbekannt'}"
        )

    async def _send(
        self,
        method: str,
        *,
        base_url: str,
        path_suffix: str,
        access_token: str,
        params: dict[str, str],
        expect_pdf: bool,
    ):
        """Execute the raw HTTP request against a Tesla mobile-app endpoint."""

        url = f"{base_url}/{path_suffix}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Tesla-User-Agent": "TeslaApp/4.10.0",
            "User-Agent": "TeslaInvoiceAutomatic/0.5.0",
            "Accept": "application/pdf" if expect_pdf else "application/json",
        }
        try:
            return await self._session.request(
                method,
                url,
                headers=headers,
                params=params,
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
        except aiohttp.ClientError as err:
            raise TeslaApiError(
                f"Tesla Ownership API konnte nicht erreicht werden: {url}. Fehler: {err}"
            ) from err

    def _build_history_query_params(self) -> dict[str, str]:
        """Build the history query exactly as Tesla's mobile app expects it."""

        params = self._build_invoice_query_params()
        params["operationName"] = "getChargingHistoryV2"
        return params

    def _build_invoice_query_params(self) -> dict[str, str]:
        """Build shared Tesla mobile-app query parameters for one vehicle."""

        return {
            "vin": self._require_config(CONF_VIN),
            "deviceLanguage": str(
                self._config.get(CONF_DEVICE_LANGUAGE, DEFAULT_DEVICE_LANGUAGE)
            ).strip(),
            "deviceCountry": str(
                self._config.get(CONF_DEVICE_COUNTRY, DEFAULT_DEVICE_COUNTRY)
            ).strip(),
            "httpLocale": str(
                self._config.get(CONF_HTTP_LOCALE, DEFAULT_HTTP_LOCALE)
            ).strip(),
        }

    async def _async_get_valid_tokens(self) -> tuple[str, str]:
        """Load cached owner tokens and refresh if they are near expiry."""

        cache = self._load_cache()
        refresh_token = str(cache.get("refresh_token") or "").strip()
        access_token = str(cache.get("access_token") or "").strip()
        if not access_token or not refresh_token:
            raise TeslaAuthenticationError(
                "Im `tesla_ha` Cache fehlen access_token oder refresh_token."
            )

        expires_at = self._read_expires_at(cache, access_token)
        if expires_at and expires_at - 300 >= time.time():
            return access_token, refresh_token

        return await self._async_refresh_tokens()

    def _read_expires_at(self, cache: dict[str, Any], access_token: str) -> float:
        """Return the known access-token expiry from cache or JWT payload."""

        raw_expires_at = cache.get("expires_at")
        if raw_expires_at:
            try:
                return float(raw_expires_at)
            except (TypeError, ValueError):
                pass

        parts = access_token.split(".")
        if len(parts) != 3:
            return 0

        payload = parts[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        try:
            decoded = json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
        except (ValueError, TypeError):
            return 0

        try:
            return float(decoded.get("exp") or 0)
        except (TypeError, ValueError):
            return 0

    def _candidate_base_urls(self) -> list[str]:
        """Build the list of ownership endpoint variants we are willing to try."""

        configured = str(
            self._config.get(CONF_OWNERSHIP_BASE_URL, DEFAULT_OWNERSHIP_BASE_URL)
        ).strip()
        unique_candidates: list[str] = []
        for candidate in (configured, *FALLBACK_OWNERSHIP_BASE_URLS):
            normalized = candidate.rstrip("/")
            if normalized and normalized not in unique_candidates:
                unique_candidates.append(normalized)
        return unique_candidates

    def _short_payload(self, payload: Any) -> str:
        """Render JSON-like payloads into short, log-friendly error snippets."""

        if isinstance(payload, (dict, list)):
            return json.dumps(payload, ensure_ascii=True)[:300]
        return str(payload)[:300]

    async def _async_refresh_tokens(self) -> tuple[str, str]:
        """Refresh the owner token using Tesla's SSO token endpoint."""

        cache_file_json = self._load_cache_file_json()
        cache_key = self._find_account_key(cache_file_json)
        if cache_key is None:
            raise TeslaAuthenticationError(
                "Im verknuepften `tesla_ha` Cache wurde kein Tesla-Account gefunden."
            )

        account = cache_file_json[cache_key]
        auth_base = str(account.get("url") or "https://auth.tesla.com/").rstrip("/")
        sso = account.get("sso") or {}
        refresh_token = str(sso.get("refresh_token") or "").strip()
        if not refresh_token:
            raise TeslaAuthenticationError(
                "Im `tesla_ha` Cache fehlt ein refresh_token. Bitte den Tesla-Login "
                "in `tesla_ha` erneut durchfuehren."
            )

        payload = {
            "grant_type": "refresh_token",
            "client_id": "ownerapi",
            "refresh_token": refresh_token,
            "scope": "openid email offline_access",
        }
        token_url = f"{auth_base}/oauth2/v3/token"
        try:
            async with self._session.post(
                token_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=DEFAULT_TIMEOUT_SECONDS,
            ) as response:
                data = await response.json(content_type=None)
        except aiohttp.ClientError as err:
            raise TeslaAuthenticationError(
                f"Tesla OAuth-Refresh konnte nicht erreicht werden: {err}"
            ) from err
        except ValueError as err:
            raise TeslaAuthenticationError(
                "Tesla OAuth-Refresh lieferte keine gueltige JSON-Antwort."
            ) from err

        if response.status != 200:
            raise TeslaAuthenticationError(
                "Tesla OAuth-Refresh fehlgeschlagen. "
                f"HTTP-Status: {response.status}, Antwort: {self._short_payload(data)}"
            )

        access_token = str(data.get("access_token") or "").strip()
        new_refresh_token = str(data.get("refresh_token") or refresh_token).strip()
        expires_in = int(data.get("expires_in") or 28800)
        if not access_token:
            raise TeslaAuthenticationError(
                "Tesla OAuth-Antwort enthaelt kein access_token."
            )

        account["sso"] = {
            **sso,
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "token_type": str(data.get("token_type") or "Bearer"),
            "expires_at": time.time() + expires_in,
        }
        cache_file_json[cache_key] = account
        self._cache_file.write_text(json.dumps(cache_file_json), encoding="utf-8")
        return access_token, new_refresh_token

    def _load_cache(self) -> dict[str, Any]:
        """Load the linked tesla_ha cache entry for the configured email."""

        cache_file_json = self._load_cache_file_json()
        cache_key = self._find_account_key(cache_file_json)
        if cache_key is None:
            raise TeslaAuthenticationError(
                "Im verknuepften `tesla_ha` Cache wurde kein Tesla-Account gefunden."
            )

        account = cache_file_json.get(cache_key)
        if not isinstance(account, dict):
            raise TeslaAuthenticationError(
                "Der verknuepfte `tesla_ha` Cache hat ein ungueltiges Account-Format."
            )

        sso = account.get("sso")
        if not isinstance(sso, dict):
            raise TeslaAuthenticationError(
                "Im verknuepften `tesla_ha` Cache fehlen die Tesla-SSO-Daten."
            )
        return sso

    def _find_account_key(self, cache_file_json: dict[str, Any]) -> str | None:
        """Locate the TeslaPy cache key for the configured email."""

        for key, value in cache_file_json.items():
            if isinstance(key, str) and key.lower() == self._email.lower() and isinstance(value, dict):
                return key

        if len(cache_file_json) == 1:
            only_key, only_value = next(iter(cache_file_json.items()))
            if isinstance(only_key, str) and isinstance(only_value, dict) and isinstance(only_value.get("sso"), dict):
                return only_key

        return None

    def _load_cache_file_json(self) -> dict[str, Any]:
        """Read the shared TeslaPy cache file from tesla_ha."""

        if not self._cache_file.exists():
            raise TeslaAuthenticationError(
                f"Der `tesla_ha` Cache wurde nicht gefunden: {self._cache_file}"
            )
        try:
            data = json.loads(self._cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise TeslaAuthenticationError(
                f"Der `tesla_ha` Cache konnte nicht gelesen werden: {err}"
            ) from err
        if not isinstance(data, dict):
            raise TeslaAuthenticationError(
                "Der `tesla_ha` Cache hat kein gueltiges JSON-Objekt als Wurzel."
            )
        return data

    def _require_config(self, key: str) -> str:
        """Return one required string config value or raise a clear error."""

        value = str(self._config.get(key) or "").strip()
        if not value:
            raise TeslaAuthenticationError(
                f"Pflichtfeld '{key}' fehlt in der Tesla-Integration. "
                "Bitte die Konfiguration oeffnen und den Wert hinterlegen."
            )
        return value
