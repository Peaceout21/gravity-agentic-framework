"""FastAPI service — gravity-api."""

import logging
import os
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI(title="Gravity Agentic Framework API", version="1.0.0")

# ---------------------------------------------------------------------------
# Lazy-initialised shared components
# ---------------------------------------------------------------------------
_runtime_cache = {}  # type: dict


def _get_components():
    """Initialise backends + GraphRuntime once and cache."""
    if "graph_runtime" in _runtime_cache:
        return _runtime_cache

    from core.adapters.factory import create_backends
    from core.graph.builder import GraphRuntime
    from core.tools.edgar_client import EdgarClient
    from core.tools.extraction_engine import ExtractionEngine, GeminiAdapter, SynthesisEngine

    backends = create_backends()

    sec_identity = os.getenv("SEC_IDENTITY", "Unknown unknown@example.com")
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    gemini_model = os.getenv("GEMINI_MODEL")

    adapter = GeminiAdapter(api_key=gemini_key, model_name=gemini_model)

    _runtime_cache["state_manager"] = backends["state_manager"]
    _runtime_cache["rag_engine"] = backends["rag_engine"]
    _runtime_cache["job_queue"] = backends["job_queue"]
    _runtime_cache["graph_runtime"] = GraphRuntime(
        state_manager=backends["state_manager"],
        edgar_client=EdgarClient(sec_identity=sec_identity),
        extraction_engine=ExtractionEngine(adapter=adapter),
        rag_engine=backends["rag_engine"],
        synthesis_engine=SynthesisEngine(adapter=GeminiAdapter(api_key=gemini_key, model_name=gemini_model)),
        tickers=[],
        checkpoint_store=backends["checkpoint_store"],
    )
    return _runtime_cache


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class QueryRequest(BaseModel):
    question: str
    ticker: Optional[str] = None


class QueryResponse(BaseModel):
    question: str
    answer_markdown: str
    citations: List[str]


class IngestRequest(BaseModel):
    tickers: List[str]


class IngestResponse(BaseModel):
    mode: str
    job_id: Optional[str] = None
    filings_processed: Optional[int] = None


class FilingItem(BaseModel):
    accession_number: str
    ticker: str
    filing_url: str
    status: str
    updated_at: str


class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str


class WatchlistUpdateRequest(BaseModel):
    tickers: List[str]


class WatchlistItem(BaseModel):
    ticker: str
    created_at: str


class NotificationItem(BaseModel):
    id: int
    org_id: str
    user_id: str
    ticker: str
    accession_number: str
    notification_type: str
    title: str
    body: str
    is_read: bool
    created_at: str


class NotificationReadRequest(BaseModel):
    pass


class ReadAllRequest(BaseModel):
    ticker: Optional[str] = None
    notification_type: Optional[str] = None
    before: Optional[str] = None


class ReadAllResponse(BaseModel):
    status: str
    updated: int


class UnreadCountResponse(BaseModel):
    unread: int


class OpsHealthResponse(BaseModel):
    api: str
    db: str
    redis: str
    workers: int


class OpsMetricsResponse(BaseModel):
    queue_depths: dict
    filing_status_counts: dict
    recent_events: dict
    failed_jobs: int
    recent_failures: list


class BackfillRequest(BaseModel):
    tickers: List[str]
    per_ticker_limit: int = 8
    include_existing: bool = False
    notify: bool = False


class BackfillResponse(BaseModel):
    mode: str
    job_id: Optional[str] = None
    filings_processed: Optional[int] = None
    analyzed: Optional[int] = None
    indexed: Optional[int] = None


class AuthContext(BaseModel):
    org_id: str
    user_id: str


def _auth_context(
    x_org_id: Optional[str] = Header(default=None, alias="X-Org-Id"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    configured_api_key = os.getenv("GRAVITY_API_KEY")
    if configured_api_key and x_api_key != configured_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    org_id = (x_org_id or "default").strip()
    user_id = (x_user_id or "default").strip()
    return AuthContext(org_id=org_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
def health():
    comps = _get_components()
    db_ok = "ok"
    try:
        comps["state_manager"].list_recent_filings(limit=1)
    except Exception as exc:
        db_ok = "error: %s" % exc

    redis_ok = "not_configured"
    if comps.get("job_queue"):
        redis_ok = "ok" if comps["job_queue"].ping() else "error"

    overall = "ok" if db_ok == "ok" else "degraded"
    return HealthResponse(status=overall, database=db_ok, redis=redis_ok)


@app.get("/filings", response_model=List[FilingItem])
def list_filings(limit: int = 25):
    comps = _get_components()
    rows = comps["state_manager"].list_recent_filings(limit=limit)
    return [FilingItem(**row) for row in rows]


@app.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest, auth: AuthContext = Depends(_auth_context)):
    comps = _get_components()
    from services.notifications import create_filing_notifications

    tickers = [t.strip().upper() for t in req.tickers if t.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="No tickers provided")

    job_queue = comps.get("job_queue")
    if job_queue:
        job_id = job_queue.enqueue_ingestion(tickers)
        return IngestResponse(mode="async", job_id=job_id)

    # Sync fallback
    gr = comps["graph_runtime"]
    payloads = gr.run_ingestion_cycle(tickers)
    create_filing_notifications(comps["state_manager"], payloads, org_id=auth.org_id)
    for payload in payloads:
        analysis = gr.analyze_filing(payload)
        if analysis:
            gr.index_analysis(analysis)
    return IngestResponse(mode="sync", filings_processed=len(payloads))


@app.post("/backfill", response_model=BackfillResponse)
def backfill(req: BackfillRequest, auth: AuthContext = Depends(_auth_context)):
    comps = _get_components()
    tickers = [t.strip().upper() for t in req.tickers if t.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="No tickers provided")

    payload = {
        "tickers": tickers,
        "per_ticker_limit": req.per_ticker_limit,
        "include_existing": req.include_existing,
        "notify": req.notify,
        "org_id": auth.org_id,
    }

    job_queue = comps.get("job_queue")
    if job_queue:
        job_id = job_queue.enqueue_backfill(payload)
        return BackfillResponse(mode="async", job_id=job_id)

    from services.backfill import run_backfill

    result = run_backfill(comps["graph_runtime"], comps["state_manager"], payload)
    return BackfillResponse(
        mode="sync",
        filings_processed=result["filings_processed"],
        analyzed=result["analyzed"],
        indexed=result["indexed"],
    )


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    comps = _get_components()
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Empty question")

    answer = comps["graph_runtime"].answer_question(req.question.strip(), ticker=req.ticker)
    return QueryResponse(
        question=answer.question,
        answer_markdown=answer.answer_markdown,
        citations=answer.citations,
    )


@app.get("/watchlist", response_model=List[WatchlistItem])
def list_watchlist(auth: AuthContext = Depends(_auth_context)):
    comps = _get_components()
    rows = comps["state_manager"].list_watchlist(org_id=auth.org_id, user_id=auth.user_id)
    return [WatchlistItem(**row) for row in rows]


@app.post("/watchlist")
def add_watchlist(req: WatchlistUpdateRequest, auth: AuthContext = Depends(_auth_context)):
    comps = _get_components()
    tickers = [t.strip().upper() for t in req.tickers if t.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="No tickers provided")
    for ticker in tickers:
        comps["state_manager"].add_watchlist_ticker(org_id=auth.org_id, user_id=auth.user_id, ticker=ticker)
    return {"status": "ok", "org_id": auth.org_id, "user_id": auth.user_id, "tickers": tickers}


@app.delete("/watchlist")
def remove_watchlist(req: WatchlistUpdateRequest, auth: AuthContext = Depends(_auth_context)):
    comps = _get_components()
    tickers = [t.strip().upper() for t in req.tickers if t.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="No tickers provided")
    for ticker in tickers:
        comps["state_manager"].remove_watchlist_ticker(org_id=auth.org_id, user_id=auth.user_id, ticker=ticker)
    return {"status": "ok", "org_id": auth.org_id, "user_id": auth.user_id, "tickers": tickers}


@app.get("/notifications", response_model=List[NotificationItem])
def list_notifications(
    limit: int = 50,
    unread_only: bool = False,
    ticker: Optional[str] = None,
    notification_type: Optional[str] = None,
    auth: AuthContext = Depends(_auth_context),
):
    comps = _get_components()
    rows = comps["state_manager"].list_notifications(
        org_id=auth.org_id,
        user_id=auth.user_id,
        limit=limit,
        unread_only=unread_only,
        ticker=ticker,
        notification_type=notification_type,
    )
    return [NotificationItem(**row) for row in rows]


@app.post("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, req: NotificationReadRequest, auth: AuthContext = Depends(_auth_context)):
    comps = _get_components()
    updated = comps["state_manager"].mark_notification_read(
        org_id=auth.org_id,
        user_id=auth.user_id,
        notification_id=notification_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "ok", "notification_id": notification_id, "org_id": auth.org_id, "user_id": auth.user_id}


@app.post("/notifications/read-all", response_model=ReadAllResponse)
def read_all_notifications(req: ReadAllRequest, auth: AuthContext = Depends(_auth_context)):
    comps = _get_components()
    count = comps["state_manager"].mark_all_notifications_read(
        org_id=auth.org_id,
        user_id=auth.user_id,
        ticker=req.ticker,
        notification_type=req.notification_type,
        before=req.before,
    )
    return ReadAllResponse(status="ok", updated=count)


@app.get("/notifications/count", response_model=UnreadCountResponse)
def unread_notification_count(auth: AuthContext = Depends(_auth_context)):
    comps = _get_components()
    count = comps["state_manager"].count_unread_notifications(
        org_id=auth.org_id, user_id=auth.user_id
    )
    return UnreadCountResponse(unread=count)


@app.get("/ops/health", response_model=OpsHealthResponse)
def ops_health(auth: AuthContext = Depends(_auth_context)):
    _ = auth
    comps = _get_components()
    db_ok = "ok"
    try:
        comps["state_manager"].list_recent_filings(limit=1)
    except Exception as exc:
        db_ok = "error: %s" % exc

    redis_ok = "not_configured"
    workers = 0
    jq = comps.get("job_queue")
    if jq:
        redis_ok = "ok" if jq.ping() else "error"
        workers = jq.worker_count()

    return OpsHealthResponse(api="ok", db=db_ok, redis=redis_ok, workers=workers)


@app.get("/ops/metrics", response_model=OpsMetricsResponse)
def ops_metrics(window_minutes: int = 60, auth: AuthContext = Depends(_auth_context)):
    _ = auth
    comps = _get_components()
    sm = comps["state_manager"]

    queue_depths = {}
    failed_jobs = 0
    jq = comps.get("job_queue")
    if jq:
        queue_depths = jq.queue_depths()
        failed_jobs = jq.failed_job_count()

    return OpsMetricsResponse(
        queue_depths=queue_depths,
        filing_status_counts=sm.count_filings_by_status(),
        recent_events=sm.count_recent_events(minutes=window_minutes),
        failed_jobs=failed_jobs,
        recent_failures=sm.list_recent_failures(limit=20),
    )
