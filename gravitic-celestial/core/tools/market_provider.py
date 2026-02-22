"""Market provider contracts and US SEC adapter."""

from core.tools.edgar_client import EdgarClient


class MarketProvider(object):
    """Canonical provider interface across markets."""

    market_code = ""

    def get_latest_events(self, instruments):
        raise NotImplementedError

    def get_recent_events(self, instruments, per_instrument_limit=8):
        raise NotImplementedError

    def get_document_text(self, event_record):
        raise NotImplementedError

    def get_document_attachments(self, event_record):
        return []

    def find_primary_attachment_text(self, attachments):
        return None

    def resolve_instrument(self, ticker):
        return {"ticker": ticker, "issuer_id": "", "exchange": ""}


class USSecProvider(MarketProvider):
    """Adapter around EdgarClient implementing the market provider interface."""

    market_code = "US_SEC"
    default_exchange = "SEC"

    def __init__(self, sec_identity, timeout_seconds=20):
        self._edgar = EdgarClient(sec_identity=sec_identity, timeout_seconds=timeout_seconds)

    def _normalize_record(self, record):
        metadata = dict(getattr(record, "metadata", {}) or {})
        market = metadata.get("market") or "US_SEC"
        exchange = metadata.get("exchange") or self.default_exchange
        source = metadata.get("source") or "sec"
        source_event_id = metadata.get("source_event_id") or getattr(record, "accession_number", "")
        issuer_id = metadata.get("issuer_id") or metadata.get("cik") or ""
        document_type = metadata.get("document_type") or metadata.get("filing_type") or metadata.get("form") or ""
        currency = metadata.get("currency") or "USD"

        metadata.update(
            {
                "market": market,
                "exchange": exchange,
                "source": source,
                "source_event_id": source_event_id,
                "issuer_id": issuer_id,
                "document_type": document_type,
                "currency": currency,
            }
        )
        record.metadata = metadata
        record.market = market
        record.exchange = exchange
        record.source = source
        record.source_event_id = source_event_id
        record.issuer_id = issuer_id
        record.document_type = document_type
        record.currency = currency
        return record

    def get_latest_events(self, instruments):
        records = self._edgar.get_latest_filings(instruments)
        return [self._normalize_record(record) for record in records]

    def get_recent_events(self, instruments, per_instrument_limit=8):
        records = self._edgar.get_recent_filings(instruments, per_ticker_limit=per_instrument_limit)
        return [self._normalize_record(record) for record in records]

    def get_document_text(self, event_record):
        return self._edgar.get_filing_text(event_record)

    def get_document_attachments(self, event_record):
        return self._edgar.get_filing_attachments(event_record)

    def find_primary_attachment_text(self, attachments):
        return self._edgar.find_exhibit_991_text(attachments)

    def resolve_instrument(self, ticker):
        symbol = (ticker or "").strip().upper()
        cik = self._edgar._resolve_cik(symbol) if symbol else ""
        return {"ticker": symbol, "issuer_id": cik or "", "exchange": "SEC"}

    # Compatibility methods used by existing runtime code paths.
    def get_latest_filings(self, tickers):
        return self.get_latest_events(tickers)

    def get_recent_filings(self, tickers, per_ticker_limit=8):
        return self.get_recent_events(tickers, per_instrument_limit=per_ticker_limit)

    def get_filing_text(self, filing_record):
        return self.get_document_text(filing_record)

    def get_filing_attachments(self, filing_record):
        return self.get_document_attachments(filing_record)

    def find_exhibit_991_text(self, attachments):
        return self.find_primary_attachment_text(attachments)
