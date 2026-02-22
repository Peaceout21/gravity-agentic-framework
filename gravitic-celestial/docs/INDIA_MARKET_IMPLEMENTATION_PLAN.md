# India Market Implementation Plan (Agentic-Conformant)

## Purpose

Extend the current US SEC-first system to support India markets (NSE/BSE) without breaking existing flows, while preserving the agentic architecture:

1. Ingestion agent discovers new market events.
2. Analyst agent extracts structured signals with reflection fallback.
3. Knowledge agent indexes normalized artifacts for retrieval.
4. Synthesis agent answers with grounded citations.

This plan is designed to be implementation-safe, testable, and production-ready.

---

## Non-Negotiable Design Constraints

1. Backward compatibility: existing US endpoints and jobs must keep working with zero client changes.
2. Deterministic idempotency: same source event must not be processed twice across retries/restarts.
3. Agentic conformance: each stage remains a graph node with explicit typed payloads and observable transitions.
4. Multi-tenant safety: org/user scoping must remain enforced for watchlist, notifications, and template runs.
5. Evidence-first answers: synthesis must return citations; low-context responses must degrade safely.

---

## Target Users and Product Behavior

Primary users:
1. Analysts tracking Indian listed companies.
2. Ops users monitoring ingestion and pipeline health.

Required behavior:
1. User can watch Indian symbols and receive in-app filing/event notifications.
2. User can backfill historical Indian disclosures.
3. User can ask questions and get grounded answers from indexed Indian documents.
4. Ops can inspect volume, failures, and queue health by market.

---

## Unified Domain Contract

### Canonical Market Codes

1. `US_SEC`
2. `IN_NSE`
3. `IN_BSE`

### Canonical Document Types (India)

1. `results`
2. `shareholding_pattern`
3. `board_meeting_outcome`
4. `corporate_action`
5. `price_sensitive_disclosure`
6. `annual_report`
7. `investor_presentation`
8. `other`

### Filing/Event Record Contract

Provider outputs must normalize to one shape:

```python
{
  "market": "IN_NSE",
  "exchange": "NSE",
  "ticker": "RELIANCE",
  "issuer_id": "INE002A01018",   # ISIN (India), CIK (US)
  "source": "nse",
  "source_event_id": "nse:RELIANCE:2026-02-15:abc123",
  "accession_number": "nse:RELIANCE:2026-02-15:abc123",  # alias for compatibility
  "filing_url": "https://...",
  "filing_type": "results",
  "metadata": {
    "document_type": "results",
    "filing_date": "2026-02-15",
    "event_time_utc": "2026-02-15T08:31:00Z",
    "period_end": "2025-12-31",
    "currency": "INR",
    "language": "en"
  }
}
```

Idempotency key:
1. Prefer `(market, source_event_id)`.
2. Fallback to `(market, accession_number)` for legacy compatibility.

---

## Required Code Contracts

### 1) Provider Interface

Add `core/tools/market_provider.py`:

```python
class MarketProvider(object):
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
```

Implementation mapping:
1. Current EDGAR client becomes `USSecProvider` (adapter wrapper).
2. New `NseProvider` and `BseProvider` implement same interface.

### 2) Message Contract Extension

Extend `FilingPayload` in `/Users/arjun/Documents/gravity_agentic_framework/gravitic-celestial/core/framework/messages.py`:
1. Add `market`, `exchange`, `issuer_id`, `source`, `source_event_id`.
2. Keep existing fields intact to avoid breakage.

### 3) Graph State Extension

Extend `/Users/arjun/Documents/gravity_agentic_framework/gravitic-celestial/core/graph/state.py` with:
1. `market`
2. `exchange`
3. `issuer_id`
4. `source_event_id`

### 4) Runtime Provider Selection

Add provider factory:
1. `US_SEC` -> SEC provider.
2. `IN_NSE` -> NSE provider.
3. `IN_BSE` -> BSE provider.

Wire selection via request/job payload `market` (default `US_SEC`).

---

## API Contract Changes (Backward Compatible)

### POST `/ingest`

Current:
1. `tickers: List[str]`

Add optional:
1. `market: str = "US_SEC"`
2. `exchange: Optional[str]`

### POST `/backfill`

Add optional:
1. `market: str = "US_SEC"`
2. `exchange: Optional[str]`
3. `document_types: Optional[List[str]]`

### Watchlist Endpoints

Support scoped instrument entries:
1. `ticker`
2. `market`
3. `exchange`

### New helper endpoints

1. `GET /markets` -> supported markets + document types.
2. `GET /instruments/resolve?ticker=&market=` -> canonical issuer mapping.

---

## Worker Job Contract

Queue payload must support both US and India:

```json
{
  "org_id": "demo-org",
  "user_id": "demo-user",
  "market": "IN_NSE",
  "exchange": "NSE",
  "tickers": ["RELIANCE", "TCS"],
  "per_ticker_limit": 8,
  "include_existing": false,
  "notify": true,
  "document_types": ["results", "board_meeting_outcome"]
}
```

Validation:
1. Reject unknown market.
2. Uppercase ticker normalization per market rules.
3. Hard cap `per_ticker_limit` (e.g., 50) to protect source + worker.

---

## Storage and Migration Plan

### Filings Table Additions

In `/Users/arjun/Documents/gravity_agentic_framework/gravitic-celestial/core/adapters/pg_schema.py` and SQLite equivalent:
1. `market TEXT NOT NULL DEFAULT 'US_SEC'`
2. `exchange TEXT`
3. `issuer_id TEXT`
4. `source TEXT`
5. `source_event_id TEXT`
6. `document_type TEXT`
7. `currency TEXT`

Indexes:
1. `idx_filings_market_updated_at (market, updated_at DESC)`
2. `idx_filings_market_ticker (market, ticker)`
3. unique `uq_filings_market_source_event (market, source_event_id)` where `source_event_id IS NOT NULL`

### Watchlists / Notifications

Add `market` and `exchange` to keep context-safe routing and filtering.

---

## Agentic Conformance Requirements

### Ingestion Node

Must:
1. Poll provider for market-specific latest events.
2. Preserve trace (`poll_provider`, `fetch_full_text`, `emit_payload` etc.).
3. Write deterministic idempotency key into state and persistence.

### Analyst Node

Must:
1. Use market-aware extraction prompt profile.
2. Execute one reflection retry when required fields missing.
3. Emit confidence labels per KPI (`high`, `medium`, `low`).
4. Route low-quality outputs to dead-letter without crashing graph.

### Knowledge Node

Must:
1. Chunk with market-aware metadata tags.
2. Index with `market`, `exchange`, `document_type`, `period_end`, `currency`.
3. Keep deterministic chunk IDs.

### Synthesis Node

Must:
1. Retrieve within market scope unless user explicitly asks cross-market.
2. Return markdown + citations.
3. Produce safe fallback brief when evidence is weak.

---

## Failure Modes and Guardrails

1. Source downtime/rate limits:
   1. exponential backoff + jitter
   2. circuit-breaker for repeated source errors
2. Parse failures:
   1. attachment fallback
   2. dead-letter with reason code
3. Duplicate events:
   1. dedupe by unique key before expensive processing
4. Hallucinated extraction:
   1. require evidence spans for key metrics
   2. confidence gating before indexing
5. Tenant bleed:
   1. enforce org/user filters on all read/write paths

---

## Implementation Phases

### Phase 1: Contracts and Schema (Foundational)

Deliverables:
1. provider interface + provider factory
2. message/state extensions
3. DB migrations + indexes
4. API request model extensions

Tests:
1. contract serialization/deserialization
2. migration idempotency
3. dedupe uniqueness behavior

Exit gate:
1. Existing US test suite remains green.
2. New schema fields present in both SQLite and Postgres paths.

### Phase 2: India Providers (NSE/BSE)

Deliverables:
1. `NseProvider`, `BseProvider`
2. instrument resolver (`ticker -> issuer_id`)
3. normalized event mapping

Tests:
1. fixture-based parser tests
2. malformed payload resilience
3. UTC timestamp normalization

Exit gate:
1. deterministic provider outputs for seeded fixtures.

### Phase 3: Pipeline Integration

Deliverables:
1. ingestion/backfill route through provider factory
2. worker payload supports market context
3. notification creation includes market scope

Tests:
1. unit tests for ingest/backfill request validation
2. worker handler tests for market payload propagation
3. idempotent re-run behavior

Exit gate:
1. same event never double-processed under retries.

### Phase 4: Analyst + RAG Market Awareness

Deliverables:
1. India extraction profile + reflection rules
2. retrieval filters by market/exchange/document type
3. filing-type hints for low-coverage answers

Tests:
1. KPI inference with confidence labels
2. RRF determinism with market filters
3. citation grounding tests

Exit gate:
1. No uncited high-confidence numeric claim in synthesis output.

### Phase 5: UI and Ops Exposure

Deliverables:
1. watchlist market selector
2. ask templates aware of market/document coverage
3. ops dashboard by-market metrics

Tests:
1. API mode + local mode parity tests
2. notification filtering by market
3. seeded E2E notification path for India

Exit gate:
1. demo user can complete watchlist -> ingest/backfill -> notify -> ask flow for India.

### Phase 6: Production Hardening

Deliverables:
1. feature flag `ENABLE_IN_MARKET`
2. runbook for source outages and dead-letter recovery
3. SLOs and alert thresholds

Tests:
1. load test with mixed markets
2. restart/recovery checkpoint tests
3. queue saturation behavior

Exit gate:
1. p95 latency + failure rates within target under load.

---

## Test Plan (Foolproof Coverage)

Minimum required tests:
1. Unit: provider parser contracts (NSE/BSE fixtures).
2. Unit: idempotency key generation and collision behavior.
3. Unit: analyst reflection retry edge for India docs.
4. Unit: document type routing and prompt profile selection.
5. Unit: market-aware retrieval filtering.
6. Unit: tenant scoping with market dimension.
7. Integration: ingestion -> analysis -> indexing for India record fixtures.
8. Integration: backfill async job with market payload.
9. Integration: notification generation + mark-read lifecycle.
10. E2E seeded: watchlist add -> event detected -> notification -> ask with citation.

Release acceptance criteria:
1. All existing tests pass unchanged.
2. All new India tests pass deterministically.
3. No P0/P1 known defects in ingestion/notification/citation paths.

---

## Observability and Operational Controls

Add by-market metrics:
1. events discovered/min
2. parse success rate
3. dead-letter rate
4. extraction confidence distribution
5. retrieval miss rate
6. notification delivery count

Log enrichment fields:
1. `market`
2. `exchange`
3. `ticker`
4. `source_event_id`
5. `org_id`
6. `job_id`

---

## Rollout Strategy

1. Stage 0: dark launch with `ENABLE_IN_MARKET=false`, run shadow ingestion only.
2. Stage 1: internal demo org rollout.
3. Stage 2: selected analyst tenants.
4. Stage 3: general availability with runbooks and SLO alerting active.

Rollback:
1. feature-flag disable India providers
2. keep US_SEC flow unaffected
3. preserve indexed data for postmortem replay

---

## Immediate Next Build Ticket Set

1. `P0` Add provider interface + US adapter wrapper + provider factory.
2. `P0` Extend `FilingPayload`/`GraphState` and API models with market fields.
3. `P0` Add schema migrations + unique idempotency index.
4. `P1` Implement NSE provider with fixture tests.
5. `P1` Wire ingest/backfill/worker market propagation.
6. `P1` Add market-scoped watchlist + notifications.
7. `P2` Add BSE provider and cross-exchange resolver.
8. `P2` Add India extraction profiles and confidence gating.

This sequence keeps risk low and preserves constant product usability while expanding market coverage.
