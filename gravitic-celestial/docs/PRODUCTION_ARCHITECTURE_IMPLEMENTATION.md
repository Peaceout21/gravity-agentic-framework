# Production Architecture Implementation

## Summary

Implemented the full production architecture from `docs/ARCHITECTURE_500_1000_USERS.md`: three Docker Compose services (`gravity-api`, `gravity-workers`, `gravity-web`) backed by Postgres+pgvector and Redis, while preserving SQLite fallback for local development. All work lives on a dedicated feature branch.

## Related Docs

- `docs/ROLLOUT_MATRIX.md` - staged rollout gates, KPIs, and rollback criteria.
- `docs/PROGRESS_LOG.txt` - chronological experiment history and decisions.
- `docs/USER_JOURNEY.md` - layman-friendly product flow and user narrative.
- `docs/CORE_PRODUCT_SPECS.md` - end-to-end product requirements and scope.

---

## Branch & Commits

| Item | Value |
|------|-------|
| **Branch** | `feat/production-architecture` |
| **Base** | `main` (no prior commits — this is the initial codebase commit) |

### Commit 1: `26b93d7`
**Add production architecture: Postgres/pgvector, Redis queues, FastAPI, Docker Compose**

53 files changed, 3,795 insertions. Contains the full codebase plus all new production architecture files.

### Commit 2: `35f5eba`
**Add end-to-end tests for production architecture**

5 files changed, 531 insertions. Contains the complete test suite covering all new adapters, services, and wiring.

---

## What Was Built

### 1. Postgres Adapter Layer (`core/adapters/`)

A parallel set of Postgres-backed classes that implement the exact same interfaces as the existing SQLite classes. The original SQLite code was left completely untouched.

| File | Purpose | Mirrors |
|------|---------|---------|
| `__init__.py` | Package init | — |
| `pg_schema.py` | All DDL: 4 tables + pgvector extension + HNSW index | `state_manager._init_db()` + `checkpoint._init_db()` + `hybrid_rag._init_db()` |
| `pg_state_manager.py` | `PostgresStateManager` with connection pooling | `core.framework.state_manager.StateManager` |
| `pg_checkpoint_store.py` | `PostgresCheckpointStore` using JSONB | `core.graph.checkpoint.SQLiteCheckpointStore` |
| `pg_rag_engine.py` | `PostgresRAGEngine` with pgvector cosine search + BM25 + RRF | `core.tools.hybrid_rag.HybridRAGEngine` |
| `factory.py` | `create_backends()` — inspects `DATABASE_URL` / `REDIS_URL` env vars | New |
| `redis_queue.py` | `RedisJobQueue` — rq wrapper for 3 job queues | New |

#### Postgres Schema (4 tables)

```sql
-- pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- filings: accession_number PK, ticker, filing_url, status, timestamps
--   indexes on updated_at DESC and ticker

-- events: bigserial PK, topic, source, payload, created_at

-- graph_checkpoints: (graph_name, thread_id) composite PK, state_json JSONB

-- chunks: id PK, text, metadata_json JSONB, embedding vector(384)
--   HNSW index on embedding using vector_cosine_ops
```

#### Backend Factory Pattern

The `create_backends()` function in `factory.py` is the single entry point for backend selection:

- **`DATABASE_URL` set** → Postgres adapters (runs `ensure_schema()` on first call)
- **`DATABASE_URL` not set** → SQLite adapters (original behaviour, zero changes)
- **`REDIS_URL` set** → `RedisJobQueue` for async job processing
- **`REDIS_URL` not set** → `job_queue = None` (sync mode)

#### Embedding Model

- `sentence-transformers` `all-MiniLM-L6-v2` (384 dimensions)
- Lazy-loaded on first use (no startup cost if not needed)
- Replaces the placeholder Jaccard similarity from the SQLite RAG engine
- pgvector HNSW index for fast approximate nearest neighbour search

### 2. Redis Job Queue (`core/adapters/redis_queue.py`)

Three queues matching the pipeline stages:

| Queue | Job Handler | Timeout | Retries |
|-------|------------|---------|---------|
| `ingestion` | `handle_ingestion(tickers)` | 10 min | 2 |
| `analysis` | `handle_analysis(filing_payload_dict)` | 5 min | 1 |
| `knowledge` | `handle_knowledge(analysis_payload_dict)` | 5 min | 1 |

Job flow:
```
POST /ingest → enqueue "ingestion"
  → worker runs ingestion → enqueue "analysis" per filing
    → worker runs analysis → enqueue "knowledge"
      → worker indexes into RAG store
```

### 3. FastAPI Service (`services/api.py`)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Database + Redis connectivity check |
| `GET` | `/filings` | List recent filings with status |
| `POST` | `/ingest` | Trigger ingestion (async via Redis or sync fallback) |
| `POST` | `/query` | Question answering (always sync — runs query graph) |

Lazy-initialises backends and `GraphRuntime` on first request.

### 4. Worker Service (`services/worker.py`)

rq worker entry point that listens on all three queues. Each handler:
1. Lazy-initialises its own `GraphRuntime` (one per worker process)
2. Runs the appropriate LangGraph subgraph
3. Enqueues the next pipeline stage (or falls back to sync if no Redis)

Run with: `python -m services.worker`

### 5. Streamlit Dual-Mode (`ui/app.py` + `ui/api_client.py`)

The Streamlit dashboard now supports two modes:

| Mode | Trigger | Behaviour |
|------|---------|-----------|
| **API mode** | `GRAVITY_API_URL` env var set | All calls go through `GravityApiClient` HTTP wrapper |
| **Local mode** | No `GRAVITY_API_URL` | Original behaviour — direct `FrameworkRuntime` in-process |

`GravityApiClient` (`ui/api_client.py`) wraps all four API endpoints with proper timeouts and error handling.

### 6. Docker Configuration

#### `docker/Dockerfile` (multi-stage)

- **Stage 1 (builder)**: `python:3.9-slim` + gcc + libpq-dev → installs all deps from `requirements-docker.txt`
- **Stage 2 (runtime)**: `python:3.9-slim` + libpq5 → copies installed packages + app code

#### `docker/docker-compose.yml` (5 services)

| Service | Image | Ports | Depends On |
|---------|-------|-------|------------|
| `postgres` | `pgvector/pgvector:pg16` | 5432 | — |
| `redis` | `redis:7-alpine` | 6379 | — |
| `gravity-api` | App Dockerfile | 8000 | postgres (healthy), redis (healthy) |
| `gravity-workers` | App Dockerfile | — | postgres (healthy), redis (healthy) |
| `gravity-web` | App Dockerfile | 8501 | gravity-api |

All app services share one Dockerfile, differentiated by `command`. API keys and secrets pass through from host `.env` via `${VAR}` substitution.

#### `.dockerignore`

Excludes `.env`, `data/`, `.venv/`, `.git/`, `__pycache__`, docs (except README).

### 7. Modified Existing Files

| File | Change |
|------|--------|
| `main.py` | `FrameworkRuntime.__init__` now calls `create_backends()` instead of hardcoding SQLite paths. 3 imports replaced, ~8 lines changed. |
| `ui/app.py` | Complete rewrite to support dual-mode (API vs local). Original local-mode behaviour preserved. |
| `requirements.txt` | Added optional production deps as comments (pointing to `requirements-docker.txt` for full set) |
| `.env.example` | Added `DATABASE_URL`, `REDIS_URL`, `GRAVITY_API_URL` |

### 8. New Requirements File

`requirements-docker.txt` — superset of `requirements.txt` plus:
- `psycopg2-binary>=2.9.9`
- `redis>=5.0.0`
- `rq>=1.16.0`
- `sentence-transformers>=2.6.0`
- `fastapi>=0.111.0`
- `uvicorn[standard]>=0.29.0`

---

## Test Suite

### New Test Files (5 files, 531 lines)

| File | Tests | What It Covers |
|------|-------|----------------|
| `tests/test_factory.py` | 3 | SQLite fallback, Postgres detection (connection error not import error), Redis queue creation |
| `tests/test_pg_adapters.py` | 8 | Schema idempotency, StateManager CRUD, CheckpointStore save/load/upsert, RAG engine add+semantic+keyword+hybrid search, RRF parity with SQLite |
| `tests/test_api_endpoints.py` | 8 | All 4 FastAPI endpoints: health (with/without Redis), filings list, ingest (sync/async modes), query, validation errors |
| `tests/test_api_client.py` | 5 | HTTP client: health, list_filings, ingest, query, query with ticker |
| `tests/test_redis_queue.py` | 5 | Queue name constants, ping, enqueue ingestion/analysis/knowledge |

### Test Results

**Full run with Postgres + Redis + sentence-transformers:**

```
$ DATABASE_URL=postgresql://gravity:gravity@localhost:5432/gravity \
  REDIS_URL=redis://localhost:6379 \
  .venv/bin/python -m unittest discover tests/ -v

Ran 35 tests in 47.293s

OK
```

**35/35 passing, 0 skipped, 0 failures.**

| Category | Count | Status |
|----------|-------|--------|
| API client (HTTP wrapper) | 5 | Pass |
| API endpoints (FastAPI TestClient) | 8 | Pass |
| SQLite checkpoint store | 1 | Pass |
| Exhibit fallback | 1 | Pass |
| Extraction retry | 1 | Pass |
| Factory (SQLite + Postgres + Redis) | 3 | Pass |
| Ingestion dedupe | 1 | Pass |
| Postgres checkpoint store | 3 | Pass |
| Postgres RAG engine (pgvector + BM25) | 2 | Pass |
| Postgres schema (DDL idempotency) | 1 | Pass |
| Postgres state manager | 2 | Pass |
| Redis queue (unit + integration) | 5 | Pass |
| RRF fusion | 1 | Pass |
| SQLite state manager | 1 | Pass |
| **Total** | **35** | **All pass** |

### Graceful Degradation

Tests skip automatically when infrastructure is unavailable:

- **No `DATABASE_URL`** → Postgres adapter tests skip (`DATABASE_URL not set`)
- **No `REDIS_URL`** → Redis integration tests skip (`REDIS_URL not set`)
- **No `psycopg2`** → Factory Postgres test skips (`psycopg2 not installed`)
- **No `redis`/`rq`** → Factory Redis test skips (`redis/rq not installed`)
- **No `sentence-transformers`** → pgvector semantic search test skips
- **No `fastapi`** → API endpoint tests skip (`fastapi not installed`)

This means `python -m unittest discover tests/` always succeeds regardless of which optional deps are installed.

---

## How to Run

### Local Development (SQLite — no Docker needed)

```bash
cd gravitic-celestial
pip install -r requirements.txt
python main.py --tickers MSFT,AAPL --run-once
```

Exactly the same as before. No `DATABASE_URL` means SQLite backends are used automatically.

### Docker Production Stack

```bash
cd gravitic-celestial

# Start everything
docker compose -f docker/docker-compose.yml up --build -d

# Verify health
curl http://localhost:8000/health
# {"status":"ok","database":"ok","redis":"ok"}

# List filings
curl http://localhost:8000/filings
# []

# Trigger ingestion
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"tickers":["MSFT"]}'
# {"mode":"async","job_id":"abc-123","filings_processed":null}

# Wait ~60s for worker processing, then check filings
curl http://localhost:8000/filings

# Ask a question
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question":"What was Microsoft revenue?"}'

# Streamlit dashboard (talks to API)
open http://localhost:8501

# Tear down
docker compose -f docker/docker-compose.yml down -v
```

### Running Integration Tests Locally

```bash
# Start just the infrastructure
docker compose -f docker/docker-compose.yml up postgres redis -d

# Install all deps
pip install -r requirements-docker.txt

# Run full test suite
DATABASE_URL=postgresql://gravity:gravity@localhost:5432/gravity \
REDIS_URL=redis://localhost:6379 \
python -m unittest discover tests/ -v
```

---

## File Tree (New & Modified)

```
gravitic-celestial/
├── core/adapters/                      # NEW — Postgres + Redis adapters
│   ├── __init__.py
│   ├── factory.py                      # Backend selection (SQLite vs Postgres)
│   ├── pg_schema.py                    # All Postgres DDL + ensure_schema()
│   ├── pg_state_manager.py             # PostgresStateManager
│   ├── pg_checkpoint_store.py          # PostgresCheckpointStore
│   ├── pg_rag_engine.py                # PostgresRAGEngine (pgvector + BM25 + RRF)
│   └── redis_queue.py                  # RedisJobQueue (3 queues via rq)
├── services/                           # NEW — API + Worker services
│   ├── __init__.py
│   ├── api.py                          # FastAPI (/health, /filings, /ingest, /query)
│   └── worker.py                       # rq worker (ingestion, analysis, knowledge)
├── ui/
│   ├── api_client.py                   # NEW — HTTP wrapper for FastAPI
│   └── app.py                          # MODIFIED — dual-mode (API vs local)
├── docker/                             # NEW — Container configuration
│   ├── Dockerfile                      # Multi-stage python:3.9-slim
│   └── docker-compose.yml              # postgres, redis, api, workers, web
├── tests/                              # NEW test files
│   ├── test_factory.py                 # Backend factory tests
│   ├── test_pg_adapters.py             # Postgres adapter integration tests
│   ├── test_api_endpoints.py           # FastAPI endpoint tests (mocked)
│   ├── test_api_client.py              # HTTP client unit tests
│   └── test_redis_queue.py             # Redis queue unit + integration tests
├── main.py                             # MODIFIED — uses create_backends() factory
├── requirements.txt                    # MODIFIED — added optional deps as comments
├── requirements-docker.txt             # NEW — full production deps
├── .env.example                        # MODIFIED — added DATABASE_URL, REDIS_URL, GRAVITY_API_URL
└── .dockerignore                       # NEW
```

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Adapter structure | Separate `core/adapters/` package | Keeps existing SQLite code completely untouched |
| Queue library | `rq` (Redis Queue) | Minimal, fits 3 job types, has retries + dead-letter. Celery is overkill. |
| Backend selection | Factory inspecting env vars | Single function returns all backends; callers stay agnostic |
| Docker base | `python:3.9-slim`, two-stage build | Keeps image small, matches Python 3.9 constraint |
| Schema management | Inline `CREATE TABLE IF NOT EXISTS` | Matches existing pattern; only 4 tables. No Alembic needed. |
| Embeddings | `all-MiniLM-L6-v2` (384-dim) | Lightweight, CPU-only, replaces placeholder Jaccard similarity |
| pgvector index | HNSW (not IVFFlat) | Works well on small datasets, no data-dependent tuning needed |
| Test strategy | Skip-based graceful degradation | Tests always pass regardless of which infra is available |
