# Release Notes - P0 Hardening and Trust Cues

## Release
- Branch: `codex/sota-rollout-implementation`
- Commit: `e590baa9`
- Date: 2026-02-20

## Executive Summary
This release moves the product from feature-complete prototype toward production-grade reliability for analyst onboarding.

The key outcomes are:
1. Safer operations under failure (replay + dead-letter diagnostics).
2. Stronger tenant safety (watchlist-scoped filing access).
3. Better answer trustworthiness (agentic derivation confidence + trace).
4. Clearer analyst experience (confidence/warning/trace visible in UI).

## What Shipped

### 1. Reliability Hardening
- Added filing replay endpoint: `POST /filings/replay`.
- Added dead-letter diagnostics on filings:
  - `dead_letter_reason`
  - `last_error`
  - `replay_count`
  - `last_replay_at`
- Added stricter graph-runtime contract handling for payloads.

### 2. Tenant and Access Safety
- Enforced watchlist-based scope for filing-facing endpoints:
  - `GET /filings`
  - `GET /filings/ticker-count`
  - `POST /filings/replay`
- Out-of-scope replay attempts are denied.

### 3. Ask Quality (Agentic)
- Added bounded metric-derivation step in query flow.
- Ask answers now carry:
  - `confidence` (0-1)
  - `derivation_trace` (human-readable reasoning steps)
- Persisted confidence and derivation trace in template run history.

### 4. UI Trust Cues
- Ask page and Dashboard Quick Ask now show:
  - Confidence label (High/Medium/Low)
  - Low-confidence warning message
  - Expandable derivation trace section

### 5. Multi-Market Foundations Included
- Added provider abstraction and India market adapters as groundwork.
- Current production recommendation remains US SEC first; non-US markets stay experimental until source reliability and economics pass rollout gates.

## Validation
- Full automated test run completed successfully.
- Result: `Ran 118 tests ... OK (skipped=16)`
- Integration/live tests retain expected skip-by-design behavior when external data conditions are unavailable.

## Product Impact
- Analysts get faster incident recovery via replay instead of manual reruns.
- Trust improves because every derived answer now includes confidence and reasoning breadcrumbs.
- Multi-user safety improves through scoped filing access by user watchlist.
- Ops gets clearer dead-letter context for triage and remediation.

## Known Limits
- SEA markets (Thailand/Philippines) are not production-enabled in this release.
- Non-US market connectors are implemented as experimental foundations and require staged rollout validation.

## Next Recommended Release Items
1. Ops quality panel for low-confidence answer-rate and template quality trends.
2. Replay action and diagnostics surfacing directly in Ops Dashboard tables.
3. SEA source pilot (small universe) behind feature flags after source-contract validation.
