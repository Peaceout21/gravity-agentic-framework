"""Ask -- Dedicated Q&A interface for filing analysis."""

import streamlit as st

from ui.components import inject_css, require_backend, setup_auth_sidebar, ticker_badge
from ui.confidence import confidence_label, low_confidence_warning, normalize_confidence

inject_css()

use_api, client, runtime, org_id, user_id = setup_auth_sidebar()
require_backend(use_api, runtime)

st.markdown("# Ask about Filings")
st.caption("Get AI-powered answers with citations from analyzed SEC filings")

if "qa_history" not in st.session_state:
    st.session_state.qa_history = []
if "template_history" not in st.session_state:
    st.session_state.template_history = []

PERIOD_OPTIONS = [
    "Latest quarter",
    "Last two quarters",
    "Latest annual",
    "Trailing twelve months",
]


def _check_ticker(ticker_value):
    """Return a warning string if ticker has no filings, else empty string."""
    if not ticker_value:
        return ""
    t = ticker_value.strip().upper()
    if not t:
        return ""
    try:
        if use_api:
            count = client.count_filings_for_ticker(t)
        else:
            count = runtime.state_manager.count_filings_for_ticker(t)
        if count == 0:
            return "No filings found for %s. Check spelling or ingest filings first." % t
    except Exception:
        pass
    return ""


def _load_persisted_template_runs():
    """Fetch persisted template runs from API or local state manager."""
    try:
        if use_api:
            return client.list_template_runs(limit=20)
        else:
            return runtime.state_manager.list_ask_template_runs(org_id, user_id, limit=20)
    except Exception:
        return []


def _load_templates():
    """Load templates from API or local state manager."""
    try:
        if use_api:
            return client.list_ask_templates()
        else:
            return runtime.state_manager.list_ask_templates(org_id, user_id)
    except Exception:
        return []


def _run_template(selected, ticker_value, period):
    """Run a template via API or locally. Returns result dict or None on error."""
    params = {}
    if period and period != "Latest quarter":
        params["period"] = period.lower()
    try:
        if use_api:
            return client.run_ask_template(
                template_id=selected["id"],
                ticker=ticker_value.strip() or None,
                params=params or None,
            )
        else:
            from services.ask_templates import run_template_query

            return run_template_query(
                state_manager=runtime.state_manager,
                graph_runtime=runtime.graph_runtime,
                org_id=org_id,
                user_id=user_id,
                template=selected,
                ticker=ticker_value.strip().upper() or None,
                params=params or None,
            )
    except Exception as exc:
        st.error("Template run failed: %s" % exc)
        return None


def _render_history(entries):
    if not entries:
        st.info("No runs yet.")
        return
    for i, entry in enumerate(reversed(entries)):
        idx = len(entries) - i
        q_text = entry.get("question") or entry.get("rendered_question", "")
        header = "**Q%d:** %s" % (idx, q_text)
        ticker = entry.get("ticker")
        if ticker:
            header = "%s %s" % (ticker_badge(ticker), header)
        st.markdown(header, unsafe_allow_html=True)
        if entry.get("relevance_label"):
            st.caption("%s | %s" % (entry.get("relevance_label", ""), entry.get("coverage_brief", "")))
        if "confidence" in entry:
            score = normalize_confidence(entry.get("confidence", 0.0))
            st.caption(confidence_label(score))
            warning = low_confidence_warning(score)
            if warning:
                st.warning(warning)
        trace = entry.get("derivation_trace", []) or []
        if trace:
            with st.expander("How this was derived", expanded=False):
                for step in trace:
                    st.markdown("- %s" % step)
        st.markdown(entry.get("answer") or entry.get("answer_markdown", ""))
        citations = entry.get("citations", [])
        if citations:
            st.caption("Sources: %s" % ", ".join(citations))
        st.divider()


tab_templates, tab_freeform = st.tabs(["Templates", "Freeform"])

with tab_templates:
    templates = _load_templates()

    if templates:
        template_map = {item["title"]: item for item in templates}
        title = st.selectbox("Template", list(template_map.keys()), key="ask_template_title")
        selected = template_map[title]
        st.markdown("*%s*" % selected.get("description", ""))
        ticker_value = st.text_input(
            "Ticker",
            value="",
            placeholder="e.g. AAPL",
            key="ask_template_ticker",
        )
        period = st.selectbox("Period", PERIOD_OPTIONS, index=0, key="ask_template_period")

        # Ticker validation warning
        ticker_warning = _check_ticker(ticker_value)
        if ticker_warning:
            st.warning(ticker_warning)

        run_col, clear_col = st.columns([1, 1])
        with run_col:
            run_clicked = st.button("Run template", type="primary", use_container_width=True)
        with clear_col:
            if st.button("Clear view", use_container_width=True):
                st.session_state.template_history = []
            st.caption("Hides runs from current view. Past runs are preserved.")

        if run_clicked:
            with st.spinner("Running template..."):
                result = _run_template(selected, ticker_value, period)
                if result:
                    st.session_state.template_history.append(
                        {
                            "question": result.get("rendered_question", ""),
                            "ticker": ticker_value.strip().upper() if ticker_value.strip() else None,
                            "relevance_label": result.get("relevance_label", ""),
                            "coverage_brief": result.get("coverage_brief", ""),
                            "answer": result.get("answer_markdown", ""),
                            "citations": result.get("citations", []),
                            "confidence": result.get("confidence", 0.0),
                            "derivation_trace": result.get("derivation_trace", []),
                            "run_id": result.get("run_id"),
                        }
                    )

        st.markdown("### Template Runs")

        # Merge session history with persisted runs
        session_ids = {e.get("run_id") for e in st.session_state.template_history if e.get("run_id")}
        persisted = _load_persisted_template_runs()
        # Show session entries first (most recent), then persisted entries not already shown
        merged = list(st.session_state.template_history)
        for run in persisted:
            if run.get("id") not in session_ids:
                merged.append(run)
        _render_history(merged)
    else:
        st.info("No templates configured.")

with tab_freeform:
    with st.form("qa_form", clear_on_submit=True):
        question = st.text_area(
            "Your question",
            height=100,
            placeholder="What was Microsoft's revenue growth? How did Apple's margins compare to last quarter?",
            key="qa_input",
        )

        form_col1, form_col2, form_col3 = st.columns([2, 1, 1])
        with form_col1:
            ticker_context = st.text_input(
                "Ticker context (optional)",
                value="",
                placeholder="e.g. MSFT",
                key="qa_ticker",
            )
        with form_col2:
            submit = st.form_submit_button("Ask", type="primary", use_container_width=True)
        with form_col3:
            if st.form_submit_button("Clear view", use_container_width=True):
                st.session_state.qa_history = []

    # Ticker validation for freeform
    if ticker_context and ticker_context.strip():
        ff_ticker_warning = _check_ticker(ticker_context)
        if ff_ticker_warning:
            st.warning(ff_ticker_warning)

    if submit and question.strip():
        with st.spinner("Analyzing filings..."):
            try:
                if use_api:
                    result = client.query(question.strip(), ticker=ticker_context.strip() or None)
                    answer_md = result.get("answer_markdown", "No answer generated.")
                    citations = result.get("citations", [])
                    confidence = result.get("confidence", 0.0)
                    derivation_trace = result.get("derivation_trace", [])
                else:
                    answer = runtime.graph_runtime.answer_question(question.strip(), ticker=ticker_context.strip() or None)
                    answer_md = answer.answer_markdown
                    citations = answer.citations
                    confidence = getattr(answer, "confidence", 0.0)
                    derivation_trace = getattr(answer, "derivation_trace", [])

                st.session_state.qa_history.append(
                    {
                        "question": question.strip(),
                        "ticker": ticker_context.strip().upper() if ticker_context.strip() else None,
                        "answer": answer_md,
                        "citations": citations,
                        "confidence": confidence,
                        "derivation_trace": derivation_trace,
                    }
                )
            except Exception as exc:
                st.session_state.qa_history.append(
                    {
                        "question": question.strip(),
                        "ticker": ticker_context.strip().upper() if ticker_context.strip() else None,
                        "answer": "Error: %s" % exc,
                        "citations": [],
                        "confidence": 0.0,
                        "derivation_trace": [],
                    }
                )

    if not st.session_state.qa_history:
        st.markdown("---")
        st.markdown("### Getting started")
        st.markdown(
            """
**Example questions you can ask:**
- What was Microsoft's revenue last quarter?
- How did Apple's gross margin compare year-over-year?
- Summarize the key guidance from the latest GOOG earnings
- What risks did Tesla highlight in their most recent 10-K?

**Tips:**
- Use the ticker context field to narrow results to a specific company
- Questions work best when filings have been ingested and analyzed first
- Answers include citations linking back to source filings
"""
        )
    else:
        _render_history(st.session_state.qa_history)
