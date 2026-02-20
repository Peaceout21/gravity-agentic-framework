"""Gravity -- Home Dashboard.

Multi-page Streamlit app entry point.
Supports two modes:
  - API mode: set GRAVITY_API_URL env var to point at the FastAPI service
  - Local mode: direct in-process FrameworkRuntime (original behaviour)
"""

import streamlit as st

st.set_page_config(
    page_title="Gravity",
    page_icon="G",
    layout="wide",
    initial_sidebar_state="expanded",
)

from ui.components import (
    format_time_ago,
    inject_css,
    metric_card,
    require_backend,
    setup_auth_sidebar,
    ticker_badge,
)
from ui.confidence import confidence_label, low_confidence_warning

inject_css()

use_api, client, runtime, org_id, user_id = setup_auth_sidebar()
require_backend(use_api, runtime)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown("# Dashboard")
st.caption("Filing intelligence at a glance")

# ---------------------------------------------------------------------------
# Top-level metrics
# ---------------------------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)

try:
    if use_api:
        unread = client.count_unread_notifications()
        filings = client.list_filings(limit=200)
        watchlist = client.list_watchlist()
    else:
        sm = runtime.state_manager
        unread = sm.count_unread_notifications(org_id, user_id)
        filings = sm.list_recent_filings(limit=200)
        watchlist = sm.list_watchlist(org_id, user_id)
except Exception as exc:
    st.error("Failed to load dashboard data: %s" % exc)
    st.stop()

total_filings = len(filings)
watchlist_count = len(watchlist)

# Status breakdown
analyzed = sum(1 for f in filings if f.get("status") == "ANALYZED")
ingested = sum(1 for f in filings if f.get("status") == "INGESTED")
failed = sum(1 for f in filings if f.get("status") in ("DEAD_LETTER", "ANALYZED_NOT_INDEXED"))

with col1:
    metric_card("Unread Alerts", str(unread), "notifications waiting" if unread else "all caught up")
with col2:
    metric_card("Filings Tracked", str(total_filings), "%d analyzed" % analyzed)
with col3:
    metric_card("Watchlist", str(watchlist_count), "tickers monitored")
with col4:
    if failed > 0:
        metric_card("Failures", str(failed), "need attention", color="status-error")
    else:
        metric_card("Pipeline", "Healthy", "%d ingested, %d analyzed" % (ingested, analyzed), color="status-ok")

st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Two-column layout: Recent Notifications + Quick Q&A
# ---------------------------------------------------------------------------
left, right = st.columns([3, 2])

# -- Recent Notifications Preview -------------------------------------------
with left:
    st.markdown("### Recent Notifications")
    try:
        if use_api:
            notifications = client.list_notifications(limit=8, unread_only=False)
        else:
            notifications = sm.list_notifications(org_id, user_id, limit=8, unread_only=False)
    except Exception:
        notifications = []

    if notifications:
        for notif in notifications:
            is_unread = not notif.get("is_read", True)
            row_class = "notif-row unread" if is_unread else "notif-row"
            badge = ticker_badge(notif.get("ticker", ""))
            time_str = format_time_ago(notif.get("created_at", ""))
            read_marker = " **NEW**" if is_unread else ""

            st.markdown(
                """<div class="%s">
                    <div class="notif-title">%s %s%s</div>
                    <div class="notif-body">%s</div>
                    <div class="notif-meta">%s &middot; %s</div>
                </div>""" % (
                    row_class,
                    badge,
                    notif.get("title", ""),
                    read_marker,
                    (notif.get("body", "")[:120] + "...") if len(notif.get("body", "")) > 120 else notif.get("body", ""),
                    notif.get("notification_type", ""),
                    time_str,
                ),
                unsafe_allow_html=True,
            )

        st.page_link("pages/1_Notifications.py", label="View all notifications", icon=None)
    else:
        st.info("No notifications yet. Add tickers to your watchlist and run ingestion to get started.")

# -- Quick Q&A -------------------------------------------------------------
with right:
    st.markdown("### Quick Ask")
    try:
        if use_api:
            _dash_templates = client.list_ask_templates()
        else:
            _dash_templates = sm.list_ask_templates(org_id, user_id)
    except Exception:
        _dash_templates = []
    if _dash_templates:
        template_options = {item["title"]: item for item in _dash_templates}
        selected_template_title = st.selectbox(
            "Template prompt",
            options=list(template_options.keys()),
            key="dash_template_select",
        )
        selected_template = template_options[selected_template_title]
        template_ticker = st.text_input(
            "Template ticker",
            value="",
            placeholder="e.g. MSFT",
            key="dash_template_ticker",
        )
        _dash_period_options = ["Latest quarter", "Last two quarters", "Latest annual", "Trailing twelve months"]
        dash_period = st.selectbox("Period", _dash_period_options, index=0, key="dash_template_period")
        # Ticker validation
        if template_ticker and template_ticker.strip():
            try:
                if use_api:
                    _tc = client.count_filings_for_ticker(template_ticker.strip())
                else:
                    _tc = sm.count_filings_for_ticker(template_ticker.strip())
                if _tc == 0:
                    st.warning("No filings found for %s. Check spelling or ingest filings first." % template_ticker.strip().upper())
            except Exception:
                pass
        if st.button("Run template", key="dash_run_template", use_container_width=True):
            with st.spinner("Running template..."):
                try:
                    _params = {}
                    if dash_period and dash_period != "Latest quarter":
                        _params["period"] = dash_period.lower()
                    if use_api:
                        result = client.run_ask_template(
                            template_id=selected_template["id"],
                            ticker=template_ticker.strip() or None,
                            params=_params or None,
                        )
                    else:
                        from services.ask_templates import run_template_query
                        result = run_template_query(
                            state_manager=sm,
                            graph_runtime=runtime.graph_runtime,
                            org_id=org_id,
                            user_id=user_id,
                            template=selected_template,
                            ticker=template_ticker.strip().upper() or None,
                            params=_params or None,
                        )
                    st.caption("%s | %s" % (result.get("relevance_label", ""), result.get("coverage_brief", "")))
                    st.caption(confidence_label(result.get("confidence", 0.0)))
                    _template_warning = low_confidence_warning(result.get("confidence", 0.0))
                    if _template_warning:
                        st.warning(_template_warning)
                    _trace = result.get("derivation_trace", []) or []
                    if _trace:
                        with st.expander("How this was derived", expanded=False):
                            for _step in _trace:
                                st.markdown("- %s" % _step)
                    st.markdown(result.get("answer_markdown", "No answer generated."))
                    if result.get("citations"):
                        st.caption("Sources: %s" % ", ".join(result["citations"]))
                except Exception as exc:
                    st.error("Template run failed: %s" % exc)
        st.markdown("---")
    question = st.text_area(
        "Ask about filings",
        height=120,
        placeholder="What was Microsoft's revenue growth last quarter?",
        key="dash_question",
        label_visibility="collapsed",
    )
    ticker_filter = st.text_input("Ticker context (optional)", value="", key="dash_ticker", placeholder="e.g. MSFT")
    if ticker_filter and ticker_filter.strip():
        try:
            if use_api:
                _ffc = client.count_filings_for_ticker(ticker_filter.strip())
            else:
                _ffc = sm.count_filings_for_ticker(ticker_filter.strip())
            if _ffc == 0:
                st.warning("No filings found for %s." % ticker_filter.strip().upper())
        except Exception:
            pass

    if st.button("Ask", key="dash_ask", type="primary", use_container_width=True):
        if not question.strip():
            st.warning("Enter a question first.")
        else:
            with st.spinner("Thinking..."):
                try:
                    if use_api:
                        result = client.query(question.strip(), ticker=ticker_filter.strip() or None)
                        st.markdown(result.get("answer_markdown", "No answer generated."))
                        citations = result.get("citations", [])
                        confidence = result.get("confidence", 0.0)
                        derivation_trace = result.get("derivation_trace", [])
                    else:
                        answer = runtime.graph_runtime.answer_question(question.strip(), ticker=ticker_filter.strip() or None)
                        st.markdown(answer.answer_markdown)
                        citations = answer.citations
                        confidence = getattr(answer, "confidence", 0.0)
                        derivation_trace = getattr(answer, "derivation_trace", [])

                    st.caption(confidence_label(confidence))
                    _warning = low_confidence_warning(confidence)
                    if _warning:
                        st.warning(_warning)
                    if derivation_trace:
                        with st.expander("How this was derived", expanded=False):
                            for _step in derivation_trace:
                                st.markdown("- %s" % _step)

                    if citations:
                        st.caption("Sources: %s" % ", ".join(citations))
                except Exception as exc:
                    st.error("Query failed: %s" % exc)

    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)

    # Watchlist quick view
    st.markdown("### Your Watchlist")
    if watchlist:
        badges_html = " ".join(ticker_badge(w.get("ticker", "")) for w in watchlist)
        st.markdown(badges_html, unsafe_allow_html=True)
    else:
        st.caption("No tickers watched yet.")
    st.page_link("pages/2_Watchlist.py", label="Manage watchlist")

# ---------------------------------------------------------------------------
# Recent Filings table
# ---------------------------------------------------------------------------
st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)
st.markdown("### Recent Filings")

recent = filings[:15]
if recent:
    st.dataframe(
        recent,
        use_container_width=True,
        column_config={
            "accession_number": st.column_config.TextColumn("Accession", width="medium"),
            "ticker": st.column_config.TextColumn("Ticker", width="small"),
            "status": st.column_config.TextColumn("Status", width="small"),
            "updated_at": st.column_config.TextColumn("Updated", width="medium"),
            "filing_url": st.column_config.LinkColumn("Filing URL", display_text="Open"),
        },
    )
else:
    st.info("No filings processed yet. Run an ingestion cycle from the Watchlist page.")
