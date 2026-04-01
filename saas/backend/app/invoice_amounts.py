"""
Purpose: Extract invoice amounts and currencies from Tesla PDF text as a fallback when API payloads are incomplete.
Input/Output: Accepts raw PDF bytes, file paths or plain text and returns a best-effort `(amount, currency)` tuple.
Invariants: Extraction is defensive, never raises on unreadable PDFs and only returns amounts when a plausible money value was found.
Debug: If live invoices still show `unbekannt`, inspect the extracted PDF text and the chosen amount candidates in this module first.
"""

from __future__ import annotations

from io import BytesIO
import logging
from pathlib import Path
import re
from decimal import Decimal, InvalidOperation

try:  # pragma: no cover - optional locally, installed in Docker runtime
    from pypdf import PdfReader
except ModuleNotFoundError:  # pragma: no cover - local fallback
    PdfReader = None


logger = logging.getLogger(__name__)
DEFAULT_CURRENCY = "EUR"
SUMMARY_KEYWORDS = (
    "gesamt",
    "summe",
    "betrag",
    "endbetrag",
    "rechnungsbetrag",
    "zu zahlen",
    "total",
    "total amount",
    "invoice total",
    "amount due",
)
MONEY_VALUE_PATTERN = re.compile(r"-?(?:\d{1,3}(?:[.\s]\d{3})+|\d+)[.,]\d{2}")
PREFIX_CURRENCY_PATTERN = re.compile(
    r"(?P<currency>EUR|USD|GBP|CHF|€|\$|£)\s*(?P<amount>-?(?:\d{1,3}(?:[.\s]\d{3})+|\d+)[.,]\d{2})",
    re.IGNORECASE,
)
SUFFIX_CURRENCY_PATTERN = re.compile(
    r"(?P<amount>-?(?:\d{1,3}(?:[.\s]\d{3})+|\d+)[.,]\d{2})\s*(?P<currency>EUR|USD|GBP|CHF|€|\$|£)",
    re.IGNORECASE,
)


def extract_amount_and_currency_from_pdf_path(pdf_path: str | Path) -> tuple[Decimal | None, str | None]:
    """Read a PDF from disk and extract a plausible amount/currency pair."""

    path = Path(pdf_path)
    if not path.exists():
        return None, None
    try:
        return extract_amount_and_currency_from_pdf_bytes(path.read_bytes())
    except OSError:
        logger.exception("Invoice PDF could not be read for amount extraction. path=%s", path)
        return None, None


def extract_amount_and_currency_from_pdf_bytes(pdf_bytes: bytes) -> tuple[Decimal | None, str | None]:
    """Extract amount/currency from a PDF payload without surfacing parser errors to the UI."""

    if not pdf_bytes:
        return None, None
    if PdfReader is None:
        logger.debug("pypdf is not installed locally. PDF amount extraction fallback is disabled in this environment.")
        return None, None

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        text_fragments = [page.extract_text() or "" for page in reader.pages]
    except Exception:  # pragma: no cover - depends on external PDF structure
        logger.exception("Invoice PDF parsing failed during amount extraction.")
        return None, None

    return extract_amount_and_currency_from_text("\n".join(text_fragments))


def extract_amount_and_currency_from_text(text: str) -> tuple[Decimal | None, str | None]:
    """Find the most plausible invoice total in free-form invoice text."""

    if not text.strip():
        return None, None

    prioritized_candidates: list[tuple[Decimal, str | None]] = []
    fallback_candidates: list[tuple[Decimal, str | None]] = []

    for raw_line in text.splitlines():
        normalized_line = " ".join(raw_line.split())
        if not normalized_line:
            continue
        line_candidates = _extract_money_candidates_from_line(normalized_line)
        if not line_candidates:
            continue
        if _line_contains_summary_keyword(normalized_line):
            prioritized_candidates.extend(line_candidates)
        else:
            fallback_candidates.extend(line_candidates)

    chosen_amount, chosen_currency = (prioritized_candidates or fallback_candidates or [(None, None)])[-1]
    if chosen_amount is None:
        return None, None
    return chosen_amount, chosen_currency or DEFAULT_CURRENCY


def _extract_money_candidates_from_line(line: str) -> list[tuple[Decimal, str | None]]:
    candidates: list[tuple[Decimal, str | None]] = []

    for pattern in (PREFIX_CURRENCY_PATTERN, SUFFIX_CURRENCY_PATTERN):
        for match in pattern.finditer(line):
            parsed_amount = _parse_decimal(match.group("amount"))
            if parsed_amount is None:
                continue
            candidates.append((parsed_amount, _normalize_currency(match.group("currency"))))

    if candidates:
        return candidates

    if not _line_contains_summary_keyword(line):
        return []

    for match in MONEY_VALUE_PATTERN.finditer(line):
        parsed_amount = _parse_decimal(match.group(0))
        if parsed_amount is None:
            continue
        candidates.append((parsed_amount, _detect_currency(line)))
    return candidates


def _line_contains_summary_keyword(line: str) -> bool:
    normalized_line = line.lower()
    return any(keyword in normalized_line for keyword in SUMMARY_KEYWORDS)


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    normalized = value.strip().replace(" ", "")
    if not normalized:
        return None
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    else:
        normalized = normalized.replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _detect_currency(text: str) -> str | None:
    normalized = text.upper()
    if "EUR" in normalized or "€" in normalized:
        return "EUR"
    if "USD" in normalized or "$" in normalized:
        return "USD"
    if "GBP" in normalized or "£" in normalized:
        return "GBP"
    if "CHF" in normalized:
        return "CHF"
    return None


def _normalize_currency(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    return {
        "€": "EUR",
        "$": "USD",
        "£": "GBP",
    }.get(normalized, normalized or None)
