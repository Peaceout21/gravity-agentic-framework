# Core Product Specs (End-to-End)

## Document Status
- Owner: Product + Engineering
- Last Updated: 2026-02-07
- Scope: Notification UX in Streamlit/API mode, Ops dashboard for pipeline health, onboarding-ready flows

## 1) Product Goals
- Deliver proactive filing intelligence for analysts with low operational overhead.
- Ensure analysts can trust and action notifications quickly.
- Ensure operators can detect, diagnose, and recover pipeline issues fast.

## 2) Target Users
- Analyst: monitors watchlist companies, asks questions, needs timely and relevant updates.
- Ops/Engineer: monitors ingestion-analysis-indexing pipeline health and investigates failures.
- Admin (later phase): manages org-level settings and policies.

## 3) Success Metrics
- Time-to-first-value (new analyst): <= 10 minutes from first login.
- Notification usefulness: >= 70% notifications opened or marked relevant within 24h.
- Pipeline reliability: >= 99% successful job completion (rolling 7d).
- Mean time to detect incident: <= 5 minutes.
- Mean time to recovery: <= 30 minutes for P1 pipeline issues.

## 4) Scope and Priorities

### P0 (must ship)
- Multi-tenant notification UX improvements in Streamlit/API mode.
- Ops dashboard (health + queue + stage-level throughput/error visibility).
- Backfill workflow surfaced in UI with progress and completion visibility.

### P1 (next)
- User notification preferences (ticker-level mute/snooze, digest windows).
- Dead-letter triage UI and replay controls.
- Alert severity model (high-impact filings first).

### P2 (later)
- External channels (WhatsApp/Telegram) as notification sinks.
- Role-based access and org admin controls.

## 5) End-to-End User Journeys

### Journey A: Analyst onboarding + first signal
1. Analyst opens app and enters `org_id`, `user_id`.
2. Analyst adds watchlist tickers.
3. Analyst triggers historical backfill for selected tickers.
4. Analyst sees notification feed populate from backfill results.
5. Analyst opens a notification and asks a follow-up question in Q&A.
6. Analyst sees cited answer and filing link.

Acceptance:
- Notifications appear only within the same `org_id` + `user_id` scope.
- Backfill completes without blocking UI.
- Clicking notification gives filing context and traceable answer path.

### Journey B: Proactive monitoring
1. System ingests new SEC filings asynchronously.
2. Matching watchlist users receive in-app notifications.
3. Analysts filter unread notifications by ticker/type and mark read.

Acceptance:
- Duplicate notifications for same `(org_id, user_id, accession)` are prevented.
- Feed refresh under 2 seconds for first page.

### Journey C: Ops incident response
1. Ops opens dashboard and sees queue depth spike + rising dead-letter count.
2. Ops drills into stage metrics and error categories.
3. Ops validates worker health and replays failed jobs.

Acceptance:
- Incident indicators surface within one dashboard refresh interval (<= 30s).
- Ops can identify failing stage and top error class without logs.

## 6) Functional Requirements

### 6.1 Notification UX (Streamlit/API mode)
- Show unread count badge in sidebar/header.
- Notification list supports:
  - Filters: `unread_only`, `ticker`, `notification_type`, date range.
  - Sorting: newest first.
  - Pagination/cursor.
- Notification row displays:
  - title, body snippet, ticker, accession, created_at, read state.
  - actions: mark read, open filing URL.
- Bulk actions:
  - mark selected read
  - mark all read (filtered scope)
- Backfill-triggered notifications are labeled as `source=backfill`.

### 6.2 Watchlist and Backfill UX
- Watchlist panel:
  - add/remove tickers
  - display current org/user scoped watchlist
- Backfill form:
  - tickers
  - per ticker limit
  - include existing
  - notify toggle
- Backfill execution modes:
  - async via queue (preferred)
  - sync fallback if queue unavailable
- Show job id + status poll widget (P0 minimal: submitted/complete/fail).

### 6.3 Ops Dashboard
- Health cards:
  - API health, DB health, Redis health, worker heartbeat.
- Queue cards:
  - ingestion, analysis, knowledge, backfill depth.
- Pipeline metrics:
  - ingestion rate/min
  - analysis success/failure
  - knowledge indexing success/failure
  - dead-letter count
  - p50/p95 stage latency
- Recent failures table:
  - timestamp, stage, ticker, accession, error class, message excerpt.

## 7) API Contract (P0)

### Existing (already implemented)
- `GET /watchlist`
- `POST /watchlist`
- `DELETE /watchlist`
- `GET /notifications`
- `POST /notifications/{id}/read`
- `POST /backfill`

### Required header auth context
- `X-Org-Id`
- `X-User-Id`
- Optional: `X-API-Key` when server-side key is configured

### P0 API additions
- `POST /notifications/read-all`
  - Body: `{ "ticker": "optional", "notification_type": "optional", "before": "optional-iso" }`
  - Result: `{ "status": "ok", "updated": <int> }`
- `GET /ops/health`
  - Result: `{ api, db, redis, workers }`
- `GET /ops/metrics`
  - Query: `window_minutes`
  - Result: queue depth + stage counters + latency percentiles

## 8) Data Model Requirements

### Notifications
- Key fields:
  - `id`, `org_id`, `user_id`, `ticker`, `accession_number`, `notification_type`, `title`, `body`, `is_read`, `created_at`
- Additions for P0:
  - `source` (`ingestion` | `backfill`)
  - `metadata_json` (optional structured context)
- Constraint:
  - unique index on `(org_id, user_id, accession_number, notification_type, source)` to suppress duplicates

### Observability Metrics (storage options)
- P0 minimal:
  - use `events` table + in-memory queue stats polling
- P1:
  - persist aggregated minute buckets for trend charts

## 9) Non-Functional Requirements
- Latency:
  - `GET /notifications` p95 < 500ms for first page
  - Dashboard summary APIs p95 < 800ms
- Reliability:
  - API and worker recover after restart using durable stores
- Security:
  - strict tenant/user scoping on all watchlist + notification endpoints
  - no cross-tenant reads/writes
- Auditability:
  - event log entries for backfill start/end and notification fanout counts

## 10) Rollout Plan

### Phase 1: Notification UX hardening
- Add unread badge, filters, pagination, read-all endpoint.
- Add dedupe unique constraint and source metadata.
- Tests: API contract + UI client + tenant boundary tests.

### Phase 2: Backfill UX + status visibility
- Backfill form + job status poll in Streamlit.
- Add completion counters in API response payload.
- Tests: seeded deterministic E2E for watchlist->backfill->notification.

### Phase 3: Ops dashboard v1
- Health/queue/throughput/error cards and recent failures table.
- Add ops API endpoints.
- Tests: endpoint contract tests with mocked queue/state.

### Phase 4: Production hardening
- SLO alarms, dead-letter replay, runbook.
- Canary rollout and load test for 500-1000 users.

## 11) Test Plan (Decision Complete)

### Unit
- Notification repository methods (filtering, pagination, mark read/read-all).
- Tenant isolation on all state manager methods.
- Queue metric collection adapters.

### API Contract
- Auth header enforcement and scoping.
- `read-all` semantics and update counts.
- Backfill request validation boundaries.
- Ops endpoint schema stability.

### Integration
- Docker-backed tests for:
  - backfill async flow with redis queue
  - notification creation/read/read-all
  - pg schema migration idempotency
  - ops metrics endpoint with real queue data

### Seeded E2E
- Deterministic seeded filing input:
  - org A receives notification
  - org B does not
  - notification detail payload contains required context

### Performance/Load
- Simulate 500 concurrent users:
  - 70% notification feed reads
  - 20% Q&A
  - 10% watchlist/backfill actions
- Verify p95 latency and queue stability under burst filing events.

## 12) Risks and Mitigations
- SEC filing burst overload:
  - Mitigation: queue backpressure + worker autoscaling policy.
- Notification fatigue:
  - Mitigation: dedupe constraints + preference controls.
- Data leakage across tenants:
  - Mitigation: mandatory auth context and scoped queries everywhere.
- Drift between SQLite and Postgres behavior:
  - Mitigation: adapter parity tests in CI.

## 13) Definition of Done
- All P0 features implemented with passing CI fast + integration workflows.
- One-click onboarding flow produces first useful notification.
- Ops dashboard can detect and explain a simulated pipeline failure.
- Runbook updated with incident triage steps and API troubleshooting.

## 14) Implementation Backlog (Ready-to-build)
1. Notification API extensions (`read-all`, filters, pagination cursor).
2. Notification DB schema update (`source`, `metadata_json`, dedupe unique index).
3. Streamlit notification UX revamp (badge, filters, bulk actions, filing deep-link).
4. Backfill status component in Streamlit/API mode.
5. Ops API endpoints (`/ops/health`, `/ops/metrics`).
6. Streamlit ops dashboard page.
7. End-to-end integration tests for ops + notification flows.
8. Load test script and threshold assertions.

