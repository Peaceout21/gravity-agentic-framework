# Gravity Rollout Matrix

## Purpose
This matrix defines how we ship the product safely from local prototype to a repeatable go-to-market release, including success metrics, quality gates, and rollback criteria.

## Scope
- Core product: filing ingestion, analysis, retrieval, Ask, notifications, watchlist, ops dashboard.
- Markets in scope:
  - Primary: US SEC (production path).
  - Experimental: India connectors (kept on separate branch, not release-blocking).

## Rollout Stages

| Stage | Goal | Users | Entry Criteria | Exit Criteria | Owner |
|---|---|---|---|---|---|
| Stage 0 - Local Hardening | Stabilize architecture and tests | Internal | Core graphs + API + worker running locally | Test suite green; deterministic seeded E2E path validated | Eng |
| Stage 1 - Internal Alpha | Validate analyst workflow end-to-end | 3-10 internal analysts | Notifications + Ask templates + auth scoping implemented | >=90% successful ingestion runs; no P0 defects for 7 days | Eng + Product |
| Stage 2 - Design Partner Beta | Validate real usage and retention | 20-50 users | Ops dashboard + failure triage + backfill contract in place | Weekly active usage >60%; median answer latency within target | Product + Ops |
| Stage 3 - Controlled Launch | Prepare repeatable onboarding and support | 100-250 users | Runbooks, SLO alerts, onboarding docs, tenant isolation verified | SLO compliance for 14 days; support load manageable | Ops + GTM |
| Stage 4 - GTM Scale | Expand to 500-1000 users | 500-1000 users | Capacity plan tested; queue/db tuning complete | Sustained SLO and cost/user within target for 30 days | Eng + Ops + GTM |

## Metric Targets by Capability

| Capability | KPI | Target | Measurement Window | Alert Threshold |
|---|---|---|---|---|
| Ingestion | Filing detection to stored record | p95 <= 5 min | rolling 24h | p95 > 10 min |
| Analysis | Filing to structured analysis success | >= 92% success | rolling 24h | < 85% |
| Dead-letter | Ratio of dead-letter filings | <= 8% | rolling 24h | > 15% |
| Ask quality | Answers with at least 1 citation when relevant context exists | >= 90% | rolling 7d | < 80% |
| Ask latency | End-user answer latency | p95 <= 8s | rolling 24h | p95 > 15s |
| Notifications | New filing notification creation success | >= 99% | rolling 24h | < 97% |
| Multi-tenant safety | Cross-tenant data leakage | 0 incidents | continuous | any incident |
| Availability | API uptime | >= 99.5% | rolling 30d | < 99.0% |

## Release Gates (Must Pass)
1. Unit + integration test suite green on release branch.
2. Live pipeline integration test is either:
   - green in release env, or
   - consistently skipped by design when dependency unavailable (documented).
3. Backfill API + worker contract verified with seeded dataset.
4. Auth headers and row-level scoping validated with negative tests.
5. Ops dashboard surfaces queue depth, worker health, failures, and event activity.
6. No unresolved P0/P1 bugs; all P2s triaged with owners.

## Rollback Criteria
- Trigger rollback if any occurs post-release:
  - Cross-tenant data exposure.
  - API availability < 97% over 1 hour.
  - Dead-letter spike > 25% sustained over 2 hours.
  - Notification pipeline outage > 30 minutes.
- Rollback action:
  - Revert deployment to previous tagged release.
  - Freeze new backfills.
  - Keep watchlist polling on last known stable build.

## Operational Cadence
- Daily: check dead-letter trends, queue depth, and worker failures.
- Weekly: review Ask answer quality sample and template performance.
- Biweekly: review cost per active user and model/API usage.
- Monthly: re-baseline SLOs and update runbooks.

## Market Expansion Policy
- US SEC path remains production default.
- New markets (e.g., India/SEA) follow an experimental track:
  1. Source reliability assessment.
  2. Symbol/instrument resolver accuracy > 95% on sample universe.
  3. Non-blocking integration behind market selector and feature flag.
  4. Promote only after 2-week stability and data completeness review.

## Current Release Recommendation
- Ship US SEC product track now with existing hardened components.
- Keep India and future SEA integrations as experimental branches until data source reliability and economics are proven.
