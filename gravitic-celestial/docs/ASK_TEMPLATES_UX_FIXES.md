# Ask Templates UX Fixes Spec

**Branch:** `codex/ask-templates-filing-aware`
**Status:** In progress
**Date:** 2026-02-06

## Background

The Ask Templates feature shipped with filing-aware relevance scoring, coverage briefs, and a Templates/Freeform tab split on the Ask page. A product review from the analyst user persona surfaced several usability gaps that reduce trust and discoverability.

This spec covers P0, P1, and P2 fixes.

---

## P0: Backfill Filing Metadata on Existing Rows

**Problem:** Filings ingested before the templates feature have `filing_type`, `item_code`, and `filing_date` as NULL/empty. `compute_relevance()` can never match rules against these filings, so every template shows "Low relevance" even when the right filings exist.

**Fix:** Add a `backfill_filing_metadata` method to both `StateManager` and `PostgresStateManager`. This method scans filings with empty `filing_type` and attempts to infer `filing_type` from the `filing_url` (SEC EDGAR URLs encode the form type). Expose this as a one-shot API endpoint `POST /filings/backfill-metadata` and call it from the Ops Dashboard with a button.

**Acceptance criteria:**
- Filings with NULL/empty `filing_type` get populated where inferable from URL or accession number patterns
- Existing non-null metadata is never overwritten
- Method is idempotent (safe to run multiple times)

---

## P0: Enable Templates in Local Mode

**Problem:** `3_Ask.py:44-45` blocks local-mode users with "Template runs are available in API mode." But `run_template_query()` only needs `state_manager` + `graph_runtime`, both available locally. The dashboard's Quick Ask section has the same issue.

**Fix:** Wire template listing and execution through the local runtime path. In local mode, call `state_manager.list_ask_templates()` directly and use the `run_template_query()` service function with the local `state_manager` + `graph_runtime`.

**Acceptance criteria:**
- Templates tab works identically in local and API mode
- Dashboard Quick Ask shows templates in local mode
- No new dependencies required for local mode

---

## P1: Load Persisted Run History from API

**Problem:** Template runs are persisted server-side via `create_ask_template_run()` and exposed via `GET /ask/template-runs`, but the Ask page only shows `st.session_state.template_history` (ephemeral). Refreshing the page loses all visible history despite the data existing in the database.

**Fix:** On page load, fetch persisted runs from the API/state manager and display them. New runs still append to session state for immediate feedback, but the history section merges persisted + session runs, deduplicating by run_id.

**Acceptance criteria:**
- Template Runs section shows runs from previous sessions
- New runs appear immediately (no page refresh needed)
- Runs are shown in reverse chronological order

---

## P1: Explain What Filing Types a Template Needs

**Problem:** `build_coverage_brief()` says "This template may be a weak fit for the available filing types" on low relevance — but doesn't explain WHICH filing types the template needs. Analysts don't know whether to ingest more, wait for a 10-Q, or if the system is broken.

**Fix:** Pass the template's filing rules into `build_coverage_brief()` and render a hint like: "Best with: 10-Q, 10-K, 8-K Item 2.02. Available: 8-K (2026-01-15)." This tells the analyst exactly what's missing.

**Acceptance criteria:**
- Low relevance briefs list the filing types the template works best with
- Medium/High relevance briefs are unchanged (no noise)
- Hint is concise, not a wall of text

---

## P2: Expose Period Parameter in Template UI

**Problem:** Templates have `{period}` and `{compare_to}` placeholders defaulting to "latest quarter" / "previous quarter", but the UI only shows ticker input. Analysts wanting a specific time period have no way to override.

**Fix:** Add a "Period" dropdown below the ticker input with options: "Latest quarter" (default), "Last two quarters", "Latest annual", "Trailing twelve months". Map these to the `period` param in `render_question()`.

**Acceptance criteria:**
- Period dropdown appears on both Ask page Templates tab and Dashboard Quick Ask
- Default selection is "Latest quarter" (preserves current behavior)
- Selected period is passed through `params` to `run_ask_template()`

---

## P2: Ticker Validation Against Known Filings

**Problem:** Ticker inputs accept arbitrary text. Typing "MICROSOFT" or "APPL" silently returns no filings and a low-quality answer with no feedback.

**Fix:** After the user enters a ticker and before running, check if any filings exist for that ticker. If not, show a warning: "No filings found for APPL. Check spelling or ingest filings first." Don't block execution — the analyst may want to try anyway.

**Acceptance criteria:**
- Warning shown when ticker has zero filings in the system
- Warning is non-blocking (analyst can still proceed)
- Works in both API and local mode
- Applies to both Templates and Freeform tabs

---

## P2: Fix "Clear History" Semantics

**Problem:** "Clear history" buttons on Templates and Freeform tabs only clear `st.session_state`, not persisted run history. This is confusing when the user sees runs reappear after refresh (once P1 is implemented).

**Fix:** Rename the button to "Clear session view" and add a tooltip/caption clarifying it only hides runs from the current session view, not from the database. Past runs remain accessible on next page load.

**Acceptance criteria:**
- Button label changed to "Clear view"
- Caption below explains: "Hides runs from current view. Past runs are preserved."
- Behavior unchanged — only session state is cleared

---

## Files Modified

| File | Changes |
|------|---------|
| `services/ask_templates.py` | Update `build_coverage_brief()` signature to accept template rules; add filing-type hint for low relevance |
| `services/api.py` | Add `POST /filings/backfill-metadata` endpoint; add `question_template` to `AskTemplateItem` |
| `ui/api_client.py` | Add `backfill_filing_metadata()`, `list_filings_for_ticker()` methods |
| `ui/pages/3_Ask.py` | Enable local mode for templates; load persisted history; add period dropdown; add ticker validation; fix clear button |
| `ui/app.py` | Enable local mode for dashboard templates; add period dropdown; add ticker validation |
| `core/framework/state_manager.py` | Add `backfill_filing_metadata()`, `count_filings_for_ticker()` |
| `core/adapters/pg_state_manager.py` | Add `backfill_filing_metadata()`, `count_filings_for_ticker()` |
| `tests/test_ask_templates_service.py` | Add tests for updated `build_coverage_brief`, metadata backfill, ticker validation |

## Non-Goals

- Custom user-created templates (future feature)
- Multi-ticker comparison templates (future feature)
- Template run deletion from database (not needed yet)
