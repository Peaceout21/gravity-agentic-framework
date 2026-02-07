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
    question = st.text_area(
        "Ask about filings",
        height=120,
        placeholder="What was Microsoft's revenue growth last quarter?",
        key="dash_question",
        label_visibility="collapsed",
    )
    ticker_filter = st.text_input("Ticker context (optional)", value="", key="dash_ticker", placeholder="e.g. MSFT")

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
                    else:
                        answer = runtime.synthesis_agent.answer(question.strip())
                        st.markdown(answer.answer_markdown)
                        citations = answer.citations

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
