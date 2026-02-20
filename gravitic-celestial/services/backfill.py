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
    market = (request.get("market", "US_SEC") or "US_SEC").strip().upper()
    exchange = (request.get("exchange") or "").strip().upper()
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
    graph_runtime.ingestion_nodes.market = market
    graph_runtime.ingestion_nodes.exchange = exchange
    if hasattr(edgar_client, "market_code") and edgar_client.market_code != market:
        raise ValueError("Configured provider %s does not support market %s" % (edgar_client.market_code, market))

    if hasattr(edgar_client, "get_recent_events"):
        records = edgar_client.get_recent_events(instruments=tickers, per_instrument_limit=per_ticker_limit)
    else:
        records = edgar_client.get_recent_filings(tickers=tickers, per_ticker_limit=per_ticker_limit)

    payloads = []
    for record in records:
        if not include_existing and state_manager.has_accession(record.accession_number):
            continue

        if hasattr(edgar_client, "get_document_text"):
            raw_text = edgar_client.get_document_text(record)
        else:
            raw_text = edgar_client.get_filing_text(record)
        if len(raw_text or "") <= 1000:
            if hasattr(edgar_client, "get_document_attachments"):
                attachments = edgar_client.get_document_attachments(record)
            else:
                attachments = edgar_client.get_filing_attachments(record)
            if hasattr(edgar_client, "find_primary_attachment_text"):
                exhibit_text = edgar_client.find_primary_attachment_text(attachments) or ""
            else:
                exhibit_text = edgar_client.find_exhibit_991_text(attachments) or ""
            if exhibit_text and exhibit_text not in (raw_text or ""):
                raw_text = "%s\n\n%s" % (raw_text or "", exhibit_text)

        metadata = dict(getattr(record, "metadata", {}) or {})
        metadata.setdefault("market", getattr(record, "market", market))
        metadata.setdefault("exchange", getattr(record, "exchange", exchange))
        metadata.setdefault("issuer_id", getattr(record, "issuer_id", ""))
        metadata.setdefault("source", getattr(record, "source", ""))
        metadata.setdefault("source_event_id", getattr(record, "source_event_id", record.accession_number))
        metadata.setdefault("document_type", getattr(record, "document_type", ""))
        metadata.setdefault("currency", getattr(record, "currency", ""))

        payload = FilingPayload(
            market=metadata.get("market", market),
            exchange=metadata.get("exchange", exchange),
            issuer_id=metadata.get("issuer_id", ""),
            source=metadata.get("source", ""),
            source_event_id=metadata.get("source_event_id", record.accession_number),
            ticker=record.ticker,
            accession_number=record.accession_number,
            filing_url=record.filing_url,
            raw_text=raw_text or "",
            metadata=metadata,
        )
        metadata = dict(payload.metadata or {})
        item_code = metadata.get("item_code") or metadata.get("items") or ""
        if isinstance(item_code, list):
            item_code = ",".join(str(value) for value in item_code)
        filing_date = metadata.get("filing_date") or ""
        state_manager.mark_ingested(
            payload.accession_number,
            payload.ticker,
            payload.filing_url,
            filing_type=getattr(record, "filing_type", "") or metadata.get("filing_type") or metadata.get("form"),
            item_code=str(item_code),
            filing_date=str(filing_date),
            market=payload.market,
            exchange=payload.exchange,
            issuer_id=payload.issuer_id,
            source=payload.source,
            source_event_id=payload.source_event_id,
            document_type=metadata.get("document_type") or metadata.get("filing_type") or metadata.get("form") or "",
            currency=metadata.get("currency") or "",
        )
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
        "market": market,
        "exchange": exchange,
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
