# SOTA Agentic Implementation Plan

## Objective
Ship a production-grade, agentic filing intelligence system with strong reliability for US SEC users now, while keeping multi-market expansion pluggable.

## North Star
- Fast, trustworthy answers from filings with citations.
- Proactive notifications when relevant new filings appear.
- Deterministic operations for 500-1000 users with clear failure handling.

## Principles
1. Agentic only where it adds measurable value.
2. Deterministic defaults for ingestion/indexing; agent loops only for extraction and synthesis quality lift.
3. Evidence-first responses (citations + provenance).
4. Tenant isolation and auditability by design.

## Target SOTA Architecture

### Orchestration
- LangGraph as the control plane for:
  - ingestion graph
  - analyst extraction graph
  - knowledge/index graph
  - query/synthesis graph
- Durable checkpoints (Postgres in prod, SQLite local fallback).
- Explicit dead-letter edges and replay points per graph.

### Model and Tooling Layer
- LangChain abstractions for prompt templates, structured output parsing, retrievers.
- Gemini adapter kept behind interface for model portability.
- Optional second-model fallback (smaller/faster) for guardrail retries.

### Retrieval
- Hybrid retrieval: pgvector semantic + BM25 keyword + deterministic RRF.
- Query-time routing:
  - short factual KPI questions -> strict retrieval + concise synthesis
  - broad thesis questions -> wider recall + coverage brief
- Metadata-first filtering by ticker, form type, period before dense search.

### Agentic Enhancements (High Impact)
1. Metric derivation agent:
   - If explicit KPI missing, derive from available statements/tables using constrained calculator tools.
   - Must emit derivation trace and confidence.
2. Coverage assessor agent:
   - Scores whether context is sufficient.
   - If low coverage, returns explicit gap summary and best-next-source guidance.
3. Reflection retry policy:
   - One bounded retry for malformed extraction output with strict schema checks.

## Implementation Workstreams

## Workstream A - Reliability Core (P0)
- Harden ingestion idempotency and status transitions.
- Enforce schema validation on all inter-agent payloads.
- Ensure dead-letter entries include root cause and replay token.
- Add replay endpoint for failed filings.

Done when:
- Dead-letter ratio <= 8% over 24h in test environment.
- No duplicate accession ingestion under concurrent runs.

## Workstream B - Ask Quality and Agentic Inference (P0)
- Add metric derivation node to query graph (feature-flagged).
- Add coverage scoring + human-readable brief.
- Preserve citations + derived-value provenance in answer payload.

Done when:
- >= 90% of relevant answers include citations.
- Derived metric answers show provenance and confidence.

## Workstream C - Multi-tenant Product Readiness (P0)
- Enforce org_id/user_id on all API paths.
- Row-level scoping validation tests (positive + negative).
- Audit log for ask runs, template runs, and backfills.

Done when:
- Zero cross-tenant leakage in automated tests.

## Workstream D - Proactive Notifications (P1)
- Filing relevance classifier (rule-first, model-assisted optional).
- In-app notification prioritization (critical/high/info).
- Notification digest endpoint for dashboard and future channels.

Done when:
- Notification create success >= 99%.
- Analyst-reported noise rate below agreed threshold.

## Workstream E - Observability and Ops (P1)
- OpenTelemetry traces for API + graph runs.
- Structured logs with run_id, tenant, ticker, graph node.
- Ops dashboard SLO panels: queue depth, dead-letter trend, p95 latency.

Done when:
- Every filing and ask run traceable end-to-end.

## Workstream F - Controlled Scale (P2)
- Queue autoscaling policy for worker pools.
- Cost guardrails: token/embedding budget caps per tenant.
- Load test at 500 and 1000 users with seeded realistic traffic.

Done when:
- SLOs hold at target user load for 24h soak test.

## API/Contract Additions (Planned)
1. `POST /filings/replay` - replay failed filing by accession/run_id.
2. `GET /ask/coverage` - explicit coverage assessment for a query.
3. `POST /ask/template-run` - include `coverage_score`, `derivation_trace`, `confidence` fields.
4. `GET /ops/slo` - aggregated operational SLO metrics.

## Test Strategy (Release-Critical)
1. Unit:
- graph node contracts and branch conditions
- metric derivation correctness on seeded fixtures
- RRF determinism

2. Integration:
- filing -> analysis -> index -> ask with mocked externals
- dead-letter replay lifecycle
- tenant isolation end-to-end

3. E2E:
- seeded notification flow (deterministic)
- ask templates + freeform + coverage brief behavior

4. Non-functional:
- load tests (500/1000 users)
- failure injection (model timeout, DB failover, queue backlog)

## Delivery Phases
1. Phase 1 (1 week): P0 reliability core + replay + validation hardening.
2. Phase 2 (1 week): agentic metric derivation + coverage assessor.
3. Phase 3 (1 week): multi-tenant audit and notification prioritization.
4. Phase 4 (1 week): observability + load validation + release gate pass.

## Release Guardrails
- No P0/P1 defects open.
- Full release suite green (or documented skip-by-design where external dependency unavailable).
- Rollback plan validated with last stable tag.

## Branching Guidance
- Keep this implementation on product/release branches.
- Do not merge experimental market connectors into release path until source reliability and cost are validated.
