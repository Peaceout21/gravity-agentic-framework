"""rq worker entry point — gravity-workers.

Run with:
    rq worker ingestion analysis knowledge --url $REDIS_URL
"""

import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-initialised shared components (one per worker process)
# ---------------------------------------------------------------------------
_worker_cache = {}  # type: dict


def _get_runtime():
    if "graph_runtime" in _worker_cache:
        return _worker_cache["graph_runtime"]

    from core.adapters.factory import create_backends
    from core.graph.builder import GraphRuntime
    from core.tools.edgar_client import EdgarClient
    from core.tools.extraction_engine import ExtractionEngine, GeminiAdapter, SynthesisEngine

    backends = create_backends()

    sec_identity = os.getenv("SEC_IDENTITY", "Unknown unknown@example.com")
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    gemini_model = os.getenv("GEMINI_MODEL")
    adapter = GeminiAdapter(api_key=gemini_key, model_name=gemini_model)

    _worker_cache["backends"] = backends
    _worker_cache["graph_runtime"] = GraphRuntime(
        state_manager=backends["state_manager"],
        edgar_client=EdgarClient(sec_identity=sec_identity),
        extraction_engine=ExtractionEngine(adapter=adapter),
        rag_engine=backends["rag_engine"],
        synthesis_engine=SynthesisEngine(adapter=GeminiAdapter(api_key=gemini_key, model_name=gemini_model)),
        tickers=[],
        checkpoint_store=backends["checkpoint_store"],
    )
    return _worker_cache["graph_runtime"]


def _get_job_queue():
    if "job_queue" not in _worker_cache:
        _get_runtime()  # ensure backends are initialised
    return _worker_cache["backends"].get("job_queue")


# ---------------------------------------------------------------------------
# Job handlers (referenced by string in rq enqueue)
# ---------------------------------------------------------------------------

def handle_ingestion(tickers):
    """Run ingestion cycle for the given tickers.

    For each filing discovered, enqueues an analysis job.
    """
    logger.info("handle_ingestion: tickers=%s", tickers)
    gr = _get_runtime()
    backends = _worker_cache.get("backends", {})
    from services.notifications import create_filing_notifications

    payloads = gr.run_ingestion_cycle(tickers)
    create_filing_notifications(backends["state_manager"], payloads, org_id="default")
    logger.info("Ingestion found %d filings", len(payloads))

    job_queue = _get_job_queue()
    for payload in payloads:
        payload_dict = payload.dict() if hasattr(payload, "dict") else dict(payload)
        if job_queue:
            job_queue.enqueue_analysis(payload_dict)
        else:
            # Sync fallback inside worker
            _handle_analysis_sync(payload_dict)

    return {"filings_found": len(payloads)}


def handle_backfill(backfill_request):
    """Run a historical backfill job."""
    logger.info("handle_backfill: tickers=%s", backfill_request.get("tickers", []))
    from services.backfill import run_backfill

    gr = _get_runtime()
    backends = _worker_cache.get("backends", {})
    result = run_backfill(gr, backends["state_manager"], backfill_request)
    logger.info("Backfill complete: processed=%s analyzed=%s", result["filings_processed"], result["analyzed"])
    return result


def handle_analysis(filing_payload_dict):
    """Analyse a single filing, then enqueue knowledge indexing."""
    from core.framework.messages import FilingPayload

    logger.info("handle_analysis: %s", filing_payload_dict.get("accession_number", "?"))
    gr = _get_runtime()

    payload = FilingPayload(**filing_payload_dict)
    analysis = gr.analyze_filing(payload)
    if analysis is None:
        logger.warning("Analysis failed (dead-lettered) for %s", payload.accession_number)
        return {"status": "dead_letter"}

    analysis_dict = analysis.dict() if hasattr(analysis, "dict") else dict(analysis)
    job_queue = _get_job_queue()
    if job_queue:
        job_queue.enqueue_knowledge(analysis_dict)
    else:
        handle_knowledge(analysis_dict)

    return {"status": "analyzed", "accession_number": payload.accession_number}


def handle_knowledge(analysis_payload_dict):
    """Index an analysis payload into the RAG store."""
    from core.framework.messages import AnalysisPayload

    logger.info("handle_knowledge: %s", analysis_payload_dict.get("accession_number", "?"))
    gr = _get_runtime()
    payload = AnalysisPayload(**analysis_payload_dict)
    receipt = gr.index_analysis(payload)
    logger.info("Indexed %d chunks for %s", receipt.chunk_count if receipt else 0, payload.accession_number)
    return {"status": "indexed", "accession_number": payload.accession_number}


def _handle_analysis_sync(filing_payload_dict):
    """Sync fallback: analyse + index in one call."""
    result = handle_analysis(filing_payload_dict)
    return result


# ---------------------------------------------------------------------------
# CLI entry point: run the rq worker
# ---------------------------------------------------------------------------

def main():
    """Start rq worker listening on ingestion, analysis, knowledge queues."""
    from redis import Redis
    from rq import Worker

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis_conn = Redis.from_url(redis_url)

    queues = ["ingestion", "analysis", "knowledge", "backfill"]
    logger.info("Starting rq worker on queues: %s", queues)
    worker = Worker(queues, connection=redis_conn)
    worker.work()


if __name__ == "__main__":
    main()
