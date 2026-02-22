"""India market providers (NSE/BSE) using normalized filing records."""

import datetime as _dt
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

from core.tools.edgar_client import FilingRecord, html_to_text
from core.tools.market_provider import MarketProvider

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

logger = logging.getLogger(__name__)


def _to_utc_iso(value):
    # type: (Any) -> str
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""

    # ISO first, including trailing Z.
    try:
        parsed = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            if ZoneInfo is not None:
                parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            else:
                parsed = parsed.replace(tzinfo=_dt.timezone(_dt.timedelta(hours=5, minutes=30)))
        return parsed.astimezone(_dt.timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        pass

    formats = (
        "%d-%b-%Y %H:%M:%S",
        "%d-%b-%Y %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d-%b-%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            parsed = _dt.datetime.strptime(text, fmt)
            if ZoneInfo is not None:
                parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            else:
                parsed = parsed.replace(tzinfo=_dt.timezone(_dt.timedelta(hours=5, minutes=30)))
            return parsed.astimezone(_dt.timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            continue
    return ""


def _as_date(value):
    # type: (Any) -> str
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            parsed = _dt.datetime.strptime(text, fmt)
            return parsed.date().isoformat()
        except Exception:
            continue
    utc = _to_utc_iso(text)
    if utc:
        return utc[:10]
    return ""


def _slugify(value):
    # type: (str) -> str
    return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")


def _map_document_type(subject):
    # type: (str) -> str
    s = (subject or "").strip().lower()
    if not s:
        return "other"
    if "result" in s or "financial" in s:
        return "results"
    if "shareholding" in s:
        return "shareholding_pattern"
    if "board meeting" in s or "outcome" in s:
        return "board_meeting_outcome"
    if "dividend" in s or "split" in s or "bonus" in s or "buyback" in s:
        return "corporate_action"
    if "annual report" in s:
        return "annual_report"
    if "presentation" in s or "investor" in s:
        return "investor_presentation"
    if "disclosure" in s or "regulation" in s or "intimation" in s:
        return "price_sensitive_disclosure"
    return "other"


class _IndiaBaseProvider(MarketProvider):
    market_code = ""
    exchange_code = ""
    source_code = ""
    api_url = ""
    files_base_url = ""

    def __init__(self, timeout_seconds=20, session=None):
        self.timeout_seconds = timeout_seconds
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "GravityAgent/1.0 (research@gravity.local)",
                "Accept": "application/json, text/plain, */*",
            }
        )

    def resolve_instrument(self, ticker):
        # type: (str) -> Dict[str, str]
        t = (ticker or "").strip().upper()
        return {"ticker": t, "issuer_id": "", "exchange": self.exchange_code}

    def _request_json(self, url):
        # type: (str) -> Any
        try:
            res = self._session.get(url, timeout=self.timeout_seconds)
            if res.status_code != 200:
                return None
            return res.json()
        except Exception:
            logger.exception("India provider JSON request failed url=%s", url)
            return None

    def _request_text(self, url):
        # type: (str) -> str
        try:
            res = self._session.get(url, timeout=self.timeout_seconds)
            if res.status_code != 200:
                return ""
            return res.text
        except Exception:
            logger.exception("India provider text request failed url=%s", url)
            return ""

    def _event_id(self, ticker, raw):
        # type: (str, Dict[str, Any]) -> str
        explicit = (
            raw.get("source_event_id")
            or raw.get("event_id")
            or raw.get("newsid")
            or raw.get("id")
            or raw.get("sr_no")
            or raw.get("SCRIP_CD")
        )
        timestamp = _to_utc_iso(
            raw.get("event_time")
            or raw.get("an_dt")
            or raw.get("announcement_time")
            or raw.get("submittedDate")
            or raw.get("DissemDT")
            or raw.get("date")
        )
        if explicit:
            return "%s:%s:%s" % (self.source_code, ticker, explicit)
        if timestamp:
            return "%s:%s:%s" % (self.source_code, ticker, timestamp)
        return "%s:%s:%s" % (self.source_code, ticker, "unknown")

    def _normalize(self, ticker, raw):
        # type: (str, Dict[str, Any]) -> FilingRecord
        symbol = (
            raw.get("symbol")
            or raw.get("sm_symbol")
            or raw.get("SecurityId")
            or raw.get("SCRIP_CD")
            or ticker
        )
        symbol = str(symbol).strip().upper()

        subject = (
            raw.get("subject")
            or raw.get("desc")
            or raw.get("announcement")
            or raw.get("Headline")
            or ""
        )
        filing_type = raw.get("filing_type") or raw.get("type") or _map_document_type(subject)
        event_time_utc = _to_utc_iso(
            raw.get("event_time") or raw.get("an_dt") or raw.get("DissemDT") or raw.get("submittedDate") or raw.get("date")
        )
        filing_date = _as_date(raw.get("filing_date") or raw.get("dt") or raw.get("date") or event_time_utc)

        path = raw.get("attachment") or raw.get("attchmntFile") or raw.get("fileName") or raw.get("pdf") or raw.get("url") or ""
        filing_url = path
        if path and not str(path).startswith("http"):
            filing_url = urljoin(self.files_base_url, str(path).lstrip("/"))

        issuer_id = str(raw.get("isin") or raw.get("ISIN") or raw.get("issuer_id") or "").strip().upper()
        source_event_id = self._event_id(symbol, raw)
        document_type = raw.get("document_type") or _map_document_type(subject)

        metadata = {
            "market": self.market_code,
            "exchange": self.exchange_code,
            "source": self.source_code,
            "source_event_id": source_event_id,
            "issuer_id": issuer_id,
            "document_type": document_type,
            "filing_type": filing_type,
            "filing_date": filing_date,
            "event_time_utc": event_time_utc,
            "currency": "INR",
            "subject": str(subject or ""),
        }
        return FilingRecord(
            ticker=symbol,
            accession_number=source_event_id,
            filing_url=str(filing_url or ""),
            filing_type=str(filing_type or "other"),
            market=self.market_code,
            exchange=self.exchange_code,
            issuer_id=issuer_id,
            source=self.source_code,
            source_event_id=source_event_id,
            document_type=str(document_type or "other"),
            currency="INR",
            metadata=metadata,
        )

    def _fetch_events_for_ticker(self, ticker):
        # type: (str) -> List[Dict[str, Any]]
        url = self.api_url.format(symbol=ticker)
        payload = self._request_json(url)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            rows = payload.get("data") or payload.get("announcements") or payload.get("Table") or []
            if isinstance(rows, list):
                return rows
        return []

    def get_latest_events(self, instruments):
        # type: (List[str]) -> List[FilingRecord]
        results = []
        for t in instruments:
            ticker = (t or "").strip().upper()
            if not ticker:
                continue
            rows = self._fetch_events_for_ticker(ticker)
            if not rows:
                continue
            normalized = [self._normalize(ticker, row) for row in rows if isinstance(row, dict)]
            if not normalized:
                continue
            normalized.sort(key=lambda r: r.metadata.get("event_time_utc", ""), reverse=True)
            results.append(normalized[0])
        return results

    def get_recent_events(self, instruments, per_instrument_limit=8):
        # type: (List[str], int) -> List[FilingRecord]
        limit = max(1, int(per_instrument_limit))
        results = []
        for t in instruments:
            ticker = (t or "").strip().upper()
            if not ticker:
                continue
            rows = self._fetch_events_for_ticker(ticker)
            normalized = [self._normalize(ticker, row) for row in rows if isinstance(row, dict)]
            normalized.sort(key=lambda r: r.metadata.get("event_time_utc", ""), reverse=True)
            results.extend(normalized[:limit])
        return results

    def get_document_text(self, event_record):
        # type: (FilingRecord) -> str
        url = getattr(event_record, "filing_url", "")
        if not url:
            return ""
        raw = self._request_text(url)
        if not raw:
            return ""
        return html_to_text(raw)

    # Compatibility with current runtime names.
    def get_latest_filings(self, tickers):
        return self.get_latest_events(tickers)

    def get_recent_filings(self, tickers, per_ticker_limit=8):
        return self.get_recent_events(tickers, per_instrument_limit=per_ticker_limit)

    def get_filing_text(self, filing_record):
        return self.get_document_text(filing_record)


class NseProvider(_IndiaBaseProvider):
    market_code = "IN_NSE"
    exchange_code = "NSE"
    source_code = "nse"
    api_url = "https://www.nseindia.com/api/corporate-announcements?symbol={symbol}"
    files_base_url = "https://nsearchives.nseindia.com/"


class BseProvider(_IndiaBaseProvider):
    market_code = "IN_BSE"
    exchange_code = "BSE"
    source_code = "bse"
    api_url = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?strType=C&strPrevDate=&strScrip={symbol}"
    files_base_url = "https://www.bseindia.com/"
