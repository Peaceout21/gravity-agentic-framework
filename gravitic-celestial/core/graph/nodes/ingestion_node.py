"""LangGraph nodes for ingestion workflow."""

from core.framework.messages import FilingPayload


class IngestionNodes(object):
    def __init__(self, edgar_client, state_manager, tickers):
        self.edgar_client = edgar_client
        self.state_manager = state_manager
        self.tickers = tickers

    @staticmethod
    def _merge(state, updates):
        merged = dict(state)
        merged.update(updates)
        return merged

    def poll_edgar(self, state):
        records = self.edgar_client.get_latest_filings(self.tickers)
        queue = []
        for record in records:
            if self.state_manager.has_accession(record.accession_number):
                continue
            queue.append(
                {
                    "ticker": record.ticker,
                    "accession_number": record.accession_number,
                    "filing_url": record.filing_url,
                    "filing_type": getattr(record, "filing_type", ""),
                    "metadata": record.metadata,
                    "record": record,
                }
            )
        return self._merge(
            state,
            {
                "filings_queue": queue,
                "filing_payloads": [],
                "trace": state.get("trace", []) + ["poll_edgar"],
            },
        )

    def dedupe_check(self, state):
        return self._merge(state, {"trace": state.get("trace", []) + ["dedupe_check"]})

    def fetch_full_text(self, state):
        queue = list(state.get("filings_queue", []))
        if not queue:
            return self._merge(state, {"current_filing": {}, "raw_text": "", "trace": state.get("trace", []) + ["fetch_full_text_empty"]})

        current = queue[0]
        text = self.edgar_client.get_filing_text(current["record"])
        current["raw_text"] = text or ""
        return self._merge(
            state,
            {
                "filings_queue": queue,
                "current_filing": current,
                "raw_text": current["raw_text"],
                "trace": state.get("trace", []) + ["fetch_full_text"],
            },
        )

    def route_exhibit_logic(self, state):
        raw_text = state.get("raw_text", "")
        if not state.get("current_filing"):
            return "no_payload"
        if len(raw_text or "") <= 1000:
            return "fetch_exhibits"
        return "emit_payload"

    def fetch_exhibits(self, state):
        current = dict(state.get("current_filing", {}))
        if not current:
            return self._merge(state, {"trace": state.get("trace", []) + ["fetch_exhibits_empty"]})

        attachments = self.edgar_client.get_filing_attachments(current["record"])
        exhibit_text = self.edgar_client.find_exhibit_991_text(attachments) or ""
        current["exhibit_text"] = exhibit_text
        return self._merge(state, {"current_filing": current, "trace": state.get("trace", []) + ["fetch_exhibits"]})

    def merge_text(self, state):
        current = dict(state.get("current_filing", {}))
        raw_text = current.get("raw_text", "")
        exhibit_text = current.get("exhibit_text", "")
        merged = raw_text
        if exhibit_text and exhibit_text not in raw_text:
            merged = "%s\n\n%s" % (raw_text, exhibit_text)
        current["raw_text"] = merged
        return self._merge(state, {"current_filing": current, "raw_text": merged, "trace": state.get("trace", []) + ["merge_text"]})

    def emit_filing_payload(self, state):
        current = dict(state.get("current_filing", {}))
        queue = list(state.get("filings_queue", []))
        payloads = list(state.get("filing_payloads", []))

        if not current:
            return self._merge(state, {"trace": state.get("trace", []) + ["emit_payload_skipped"]})

        payload = FilingPayload(
            ticker=current["ticker"],
            accession_number=current["accession_number"],
            filing_url=current["filing_url"],
            raw_text=current.get("raw_text", ""),
            metadata=current.get("metadata", {}),
        )
        payloads.append(payload)
        metadata = payload.metadata or {}
        item_code = metadata.get("item_code") or metadata.get("items") or ""
        if isinstance(item_code, list):
            item_code = ",".join(str(value) for value in item_code)
        filing_date = metadata.get("filing_date") or ""
        self.state_manager.mark_ingested(
            payload.accession_number,
            payload.ticker,
            payload.filing_url,
            filing_type=current.get("filing_type") or metadata.get("filing_type") or metadata.get("form"),
            item_code=str(item_code),
            filing_date=str(filing_date),
        )

        if queue:
            queue = queue[1:]
        return self._merge(
            state,
            {
                "filing_payloads": payloads,
                "filings_queue": queue,
                "current_filing": {},
                "trace": state.get("trace", []) + ["emit_filing_payload"],
            },
        )

    def route_continue_or_end(self, state):
        queue = state.get("filings_queue", [])
        if queue:
            return "continue"
        return "end"
