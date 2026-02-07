"""Live SEC EDGAR client with Exhibit 99.1 recovery helpers."""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


@dataclass
class FilingRecord(object):
    ticker: str
    accession_number: str
    filing_url: str
    filing_type: str = "8-K"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AttachmentRecord(object):
    name: str
    description: str
    text: str


class EdgarClient(object):
    COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
    SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK%s.json"
    ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

    def __init__(self, sec_identity, provider=None, timeout_seconds=20):
        self.sec_identity = sec_identity
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": sec_identity,
                "Accept-Encoding": "gzip, deflate",
            }
        )
        self._ticker_to_cik = {}
        self._ticker_cache_path = os.path.join("data", "company_tickers_cache.json")

    def get_latest_filings(self, tickers):
        if self.provider and hasattr(self.provider, "get_latest_filings"):
            return self.provider.get_latest_filings(tickers)

        filings = []
        for ticker in tickers:
            try:
                cik = self._resolve_cik(ticker)
                if not cik:
                    logging.warning("No CIK found for ticker=%s", ticker)
                    continue

                data = self._get_json(self.SUBMISSIONS_URL % cik)
                if not data:
                    continue

                recent = data.get("filings", {}).get("recent", {})
                records = self._extract_recent_records(recent)
                for record in records:
                    if record["form"] not in ("8-K", "10-Q", "10-K"):
                        continue

                    accession = record["accessionNumber"]
                    accession_no_dashes = accession.replace("-", "")
                    primary_doc = record.get("primaryDocument")
                    if not primary_doc:
                        continue

                    filing_url = "%s/%s/%s/%s" % (
                        self.ARCHIVES_BASE,
                        str(int(cik)),
                        accession_no_dashes,
                        primary_doc,
                    )
                    directory_url = "%s/%s/%s/" % (
                        self.ARCHIVES_BASE,
                        str(int(cik)),
                        accession_no_dashes,
                    )

                    filings.append(
                        FilingRecord(
                            ticker=ticker,
                            accession_number=accession,
                            filing_url=filing_url,
                            filing_type=record["form"],
                            metadata={
                                "cik": cik,
                                "filing_date": record.get("filingDate", ""),
                                "primary_document": primary_doc,
                                "directory_url": directory_url,
                            },
                        )
                    )
                    break
            except Exception:
                logging.exception("Failed loading latest filing for ticker=%s", ticker)
        return filings

    def get_recent_filings(self, tickers, per_ticker_limit=8):
        if self.provider and hasattr(self.provider, "get_recent_filings"):
            return self.provider.get_recent_filings(tickers, per_ticker_limit=per_ticker_limit)

        filings = []
        per_ticker_limit = max(1, int(per_ticker_limit))
        for ticker in tickers:
            try:
                cik = self._resolve_cik(ticker)
                if not cik:
                    continue
                data = self._get_json(self.SUBMISSIONS_URL % cik)
                if not data:
                    continue
                recent = data.get("filings", {}).get("recent", {})
                records = self._extract_recent_records(recent)
                collected = 0
                for record in records:
                    if record["form"] not in ("8-K", "10-Q", "10-K"):
                        continue
                    accession = record["accessionNumber"]
                    accession_no_dashes = accession.replace("-", "")
                    primary_doc = record.get("primaryDocument")
                    if not primary_doc:
                        continue

                    filing_url = "%s/%s/%s/%s" % (
                        self.ARCHIVES_BASE,
                        str(int(cik)),
                        accession_no_dashes,
                        primary_doc,
                    )
                    directory_url = "%s/%s/%s/" % (
                        self.ARCHIVES_BASE,
                        str(int(cik)),
                        accession_no_dashes,
                    )
                    filings.append(
                        FilingRecord(
                            ticker=ticker,
                            accession_number=accession,
                            filing_url=filing_url,
                            filing_type=record["form"],
                            metadata={
                                "cik": cik,
                                "filing_date": record.get("filingDate", ""),
                                "primary_document": primary_doc,
                                "directory_url": directory_url,
                            },
                        )
                    )
                    collected += 1
                    if collected >= per_ticker_limit:
                        break
            except Exception:
                logging.exception("Failed loading recent filings for ticker=%s", ticker)
        return filings

    def get_filing_text(self, filing_record):
        if self.provider and hasattr(self.provider, "get_filing_text"):
            return self.provider.get_filing_text(filing_record)

        text = self._get_text(filing_record.filing_url)
        return html_to_text(text)

    def get_filing_attachments(self, filing_record):
        if self.provider and hasattr(self.provider, "get_filing_attachments"):
            return self.provider.get_filing_attachments(filing_record)

        directory_url = filing_record.metadata.get("directory_url", "")
        if not directory_url:
            return []

        index_url = urljoin(directory_url, "index.json")
        index_data = self._get_json(index_url)
        if not index_data:
            return []

        items = index_data.get("directory", {}).get("item", [])
        attachments = []
        for item in items:
            name = item.get("name", "")
            lower = name.lower()
            is_candidate = (
                "99" in lower
                or "ex" in lower
                or "press" in lower
                or lower.endswith(".htm")
                or lower.endswith(".html")
                or lower.endswith(".txt")
            )
            if not is_candidate:
                continue

            attachment_url = urljoin(directory_url, name)
            raw = self._get_text(attachment_url)
            if not raw:
                continue

            attachments.append(
                AttachmentRecord(
                    name=name,
                    description=item.get("type", ""),
                    text=html_to_text(raw),
                )
            )
        return attachments

    @staticmethod
    def find_exhibit_991_text(attachments):
        prioritized = []
        for attachment in attachments:
            signature = "%s %s" % (attachment.name.lower(), attachment.description.lower())
            if "99.1" in signature or "ex-99" in signature or "press release" in signature:
                prioritized.append(attachment)
        for attachment in prioritized:
            if attachment.text and attachment.text.strip():
                return attachment.text
        return None

    def _resolve_cik(self, ticker):
        ticker = ticker.upper()
        if ticker in self._ticker_to_cik:
            return self._ticker_to_cik[ticker]

        mapping = self._load_ticker_mapping()
        return mapping.get(ticker)

    def _load_ticker_mapping(self):
        if self._ticker_to_cik:
            return self._ticker_to_cik

        if os.path.exists(self._ticker_cache_path):
            try:
                with open(self._ticker_cache_path, "r", encoding="utf-8") as handle:
                    cached = json.load(handle)
                if isinstance(cached, dict) and cached:
                    self._ticker_to_cik = cached
                    return self._ticker_to_cik
            except Exception:
                logging.exception("Failed reading ticker cache")

        payload = self._get_json(self.COMPANY_TICKERS_URL)
        if not payload:
            return {}

        mapping = {}
        for _, entry in payload.items():
            symbol = str(entry.get("ticker", "")).upper()
            cik_number = entry.get("cik_str")
            if symbol and cik_number is not None:
                mapping[symbol] = str(cik_number).zfill(10)

        self._ticker_to_cik = mapping
        try:
            os.makedirs(os.path.dirname(self._ticker_cache_path), exist_ok=True)
            with open(self._ticker_cache_path, "w", encoding="utf-8") as handle:
                json.dump(mapping, handle)
        except Exception:
            logging.exception("Failed writing ticker cache")
        return self._ticker_to_cik

    def _extract_recent_records(self, recent):
        accessions = recent.get("accessionNumber", [])
        forms = recent.get("form", [])
        primary_docs = recent.get("primaryDocument", [])
        filing_dates = recent.get("filingDate", [])

        count = min(len(accessions), len(forms), len(primary_docs), len(filing_dates))
        rows = []
        for idx in range(count):
            rows.append(
                {
                    "accessionNumber": accessions[idx],
                    "form": forms[idx],
                    "primaryDocument": primary_docs[idx],
                    "filingDate": filing_dates[idx],
                }
            )
        return rows

    def _get_json(self, url):
        try:
            response = self._session.get(url, timeout=self.timeout_seconds)
            if response.status_code != 200:
                logging.warning("SEC JSON request failed status=%s url=%s", response.status_code, url)
                return {}
            return response.json()
        except Exception:
            logging.exception("SEC JSON request failed url=%s", url)
            return {}

    def _get_text(self, url):
        try:
            response = self._session.get(url, timeout=self.timeout_seconds)
            if response.status_code != 200:
                logging.warning("SEC text request failed status=%s url=%s", response.status_code, url)
                return ""
            return response.text
        except Exception:
            logging.exception("SEC text request failed url=%s", url)
            return ""


def html_to_text(raw_text):
    if not raw_text:
        return ""
    if "<html" not in raw_text.lower() and "<body" not in raw_text.lower():
        return raw_text
    soup = BeautifulSoup(raw_text, "html.parser")
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
