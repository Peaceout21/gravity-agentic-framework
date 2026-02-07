"""Ops Dashboard -- pipeline health, queue depths, and error visibility."""

import streamlit as st

from ui.components import health_dot, inject_css, metric_card, setup_auth_sidebar

inject_css()

use_api, client, runtime, org_id, user_id = setup_auth_sidebar()

# Ops dashboard does not require user auth context — it's system-wide

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown("# Ops Dashboard")
st.caption("Pipeline health, queue monitoring, and failure triage")

# ---------------------------------------------------------------------------
# Health Cards
# ---------------------------------------------------------------------------
st.markdown("### System Health")

try:
    if use_api:
        health = client.ops_health()
    else:
        # Local mode: build health from what we can check
        health = {"api": "ok", "db": "ok", "redis": "not_configured", "workers": 0}
        try:
            runtime.state_manager.list_recent_filings(limit=1)
        except Exception as exc:
            health["db"] = "error: %s" % exc
except Exception as exc:
    st.error("Failed to reach ops endpoint: %s" % exc)
    health = {"api": "error", "db": "unknown", "redis": "unknown", "workers": 0}

h_col1, h_col2, h_col3, h_col4 = st.columns(4)

with h_col1:
    api_status = health.get("api", "unknown")
    st.markdown(
        '<div class="metric-card">%s <b>API</b><div class="value">%s</div></div>'
        % (health_dot(api_status), api_status.upper()),
        unsafe_allow_html=True,
    )

with h_col2:
    db_status = health.get("db", "unknown")
    db_display = "OK" if db_status == "ok" else "ERROR"
    st.markdown(
        '<div class="metric-card">%s <b>Database</b><div class="value">%s</div></div>'
        % (health_dot(db_status), db_display),
        unsafe_allow_html=True,
    )

with h_col3:
    redis_status = health.get("redis", "not_configured")
    redis_display = redis_status.upper().replace("_", " ")
    st.markdown(
        '<div class="metric-card">%s <b>Redis</b><div class="value">%s</div></div>'
        % (health_dot(redis_status), redis_display),
        unsafe_allow_html=True,
    )

with h_col4:
    workers = health.get("workers", 0)
    w_status = "ok" if workers > 0 else "off"
    st.markdown(
        '<div class="metric-card">%s <b>Workers</b><div class="value">%d</div><div class="sub">active</div></div>'
        % (health_dot(w_status), workers),
        unsafe_allow_html=True,
    )

st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
window = st.selectbox("Time window", options=[15, 30, 60, 120, 360], index=2, format_func=lambda x: "%d min" % x)

try:
    if use_api:
        metrics = client.ops_metrics(window_minutes=int(window))
    else:
        sm = runtime.state_manager
        metrics = {
            "queue_depths": {},
            "filing_status_counts": sm.count_filings_by_status(),
            "recent_events": sm.count_recent_events(minutes=int(window)),
            "failed_jobs": 0,
            "recent_failures": sm.list_recent_failures(limit=20),
        }
except Exception as exc:
    st.error("Failed to load metrics: %s" % exc)
    metrics = {
        "queue_depths": {},
        "filing_status_counts": {},
        "recent_events": {},
        "failed_jobs": 0,
        "recent_failures": [],
    }

# ---------------------------------------------------------------------------
# Queue Depths
# ---------------------------------------------------------------------------
st.markdown("### Queue Depths")

queue_depths = metrics.get("queue_depths", {})
if queue_depths:
    q_cols = st.columns(len(queue_depths))
    for i, (qname, depth) in enumerate(queue_depths.items()):
        with q_cols[i]:
            color = "status-error" if depth > 50 else ("status-warn" if depth > 10 else "")
            metric_card(qname.title(), str(depth), "pending jobs", color=color)
else:
    st.info("No queue data available. Redis may not be configured.")

st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Filing Status Breakdown
# ---------------------------------------------------------------------------
st.markdown("### Filing Pipeline Status")

status_counts = metrics.get("filing_status_counts", {})
if status_counts:
    s_cols = st.columns(len(status_counts))
    status_colors = {
        "INGESTED": "",
        "ANALYZED": "status-ok",
        "ANALYZED_NOT_INDEXED": "status-warn",
        "DEAD_LETTER": "status-error",
    }
    for i, (status, count) in enumerate(sorted(status_counts.items())):
        with s_cols[i]:
            metric_card(
                status.replace("_", " ").title(),
                str(count),
                "filings",
                color=status_colors.get(status, ""),
            )
else:
    st.info("No filings processed yet.")

st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Recent Events
# ---------------------------------------------------------------------------
st.markdown("### Event Activity (last %d min)" % int(window))

events = metrics.get("recent_events", {})
if events:
    e_cols = st.columns(min(len(events), 4))
    for i, (topic, count) in enumerate(sorted(events.items())):
        with e_cols[i % 4]:
            metric_card(topic, str(count), "events")
else:
    st.info("No events in the selected window.")

# Failed jobs indicator
failed_jobs = metrics.get("failed_jobs", 0)
if failed_jobs > 0:
    st.warning("**%d failed jobs** in dead-letter queues" % failed_jobs)

st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Recent Failures Table
# ---------------------------------------------------------------------------
st.markdown("### Recent Failures")

failures = metrics.get("recent_failures", [])
if failures:
    st.dataframe(
        failures,
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
    st.success("No recent failures. Pipeline is healthy.")

# ---------------------------------------------------------------------------
# Auto-refresh
# ---------------------------------------------------------------------------
st.divider()
auto_refresh = st.checkbox("Auto-refresh every 30 seconds", value=False, key="ops_auto")
if auto_refresh:
    import time
    time.sleep(30)
    st.rerun()
