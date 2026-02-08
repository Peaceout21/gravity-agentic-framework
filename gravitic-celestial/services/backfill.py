"""Backfill orchestration shared by API and worker."""

import json

from core.framework.messages import FilingPayload
from services.notifications import create_filing_notifications


def run_backfill(graph_runtime, state_manager, request):
    """Run backfill for a batch of tickers.

    request keys:
      - tickers: list[str]
      - per_ticker_limit: int
      - include_existing: bool
      - notify: bool
      - org_id: str
    """
    tickers = [t.strip().upper() for t in request.get("tickers", []) if t and t.strip()]
    per_ticker_limit = int(request.get("per_ticker_limit", 8))
    include_existing = bool(request.get("include_existing", False))
    notify = bool(request.get("notify", False))
    org_id = request.get("org_id", "default")
    if hasattr(state_manager, "log_event"):
        try:
            state_manager.log_event(
                "BACKFILL_STARTED",
                "backfill",
                json.dumps(
                    {"org_id": org_id, "tickers": tickers, "per_ticker_limit": per_ticker_limit},
                    ensure_ascii=True,
                ),
            )
        except Exception:
            pass

    edgar_client = graph_runtime.ingestion_nodes.edgar_client
    records = edgar_client.get_recent_filings(tickers=tickers, per_ticker_limit=per_ticker_limit)

    payloads = []
    for record in records:
        if not include_existing and state_manager.has_accession(record.accession_number):
            continue

        raw_text = edgar_client.get_filing_text(record)
        if len(raw_text or "") <= 1000:
            attachments = edgar_client.get_filing_attachments(record)
            exhibit_text = edgar_client.find_exhibit_991_text(attachments) or ""
            if exhibit_text and exhibit_text not in (raw_text or ""):
                raw_text = "%s\n\n%s" % (raw_text or "", exhibit_text)

        payload = FilingPayload(
            ticker=record.ticker,
            accession_number=record.accession_number,
            filing_url=record.filing_url,
            raw_text=raw_text or "",
            metadata=record.metadata,
        )
        state_manager.mark_ingested(payload.accession_number, payload.ticker, payload.filing_url)
        payloads.append(payload)

    if notify and payloads:
        create_filing_notifications(state_manager, payloads, org_id=org_id)

    analyzed = 0
    indexed = 0
    for payload in payloads:
        analysis = graph_runtime.analyze_filing(payload)
        if analysis:
            analyzed += 1
            receipt = graph_runtime.index_analysis(analysis)
            if receipt:
                indexed += 1

    result = {
        "tickers": tickers,
        "records_found": len(records),
        "filings_processed": len(payloads),
        "analyzed": analyzed,
        "indexed": indexed,
    }
    if hasattr(state_manager, "log_event"):
        try:
            state_manager.log_event("BACKFILL_COMPLETED", "backfill", json.dumps(result, ensure_ascii=True))
        except Exception:
            pass
    return result
