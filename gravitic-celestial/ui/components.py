"""Shared UI components for multi-page Streamlit app."""

import os
from typing import Optional

import streamlit as st

GRAVITY_API_URL = os.getenv("GRAVITY_API_URL")
GRAVITY_ORG_ID = os.getenv("GRAVITY_ORG_ID", "default")
GRAVITY_USER_ID = os.getenv("GRAVITY_USER_ID", "default")
GRAVITY_API_KEY = os.getenv("GRAVITY_API_KEY")


def inject_css():
    """Inject custom CSS for a cleaner, more professional look."""
    st.markdown("""
    <style>
    /* Metric cards */
    .metric-card {
        background: linear-gradient(135deg, #f8f9fa 0%, #ffffff 100%);
        border: 1px solid #e9ecef;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.04);
    }
    .metric-card h3 {
        margin: 0 0 4px 0;
        font-size: 0.85rem;
        color: #6c757d;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .metric-card .value {
        font-size: 2rem;
        font-weight: 700;
        color: #212529;
        line-height: 1.2;
    }
    .metric-card .sub {
        font-size: 0.78rem;
        color: #adb5bd;
        margin-top: 4px;
    }

    /* Status indicators */
    .status-ok { color: #198754; }
    .status-warn { color: #fd7e14; }
    .status-error { color: #dc3545; }
    .status-off { color: #adb5bd; }

    /* Health dot */
    .health-dot {
        display: inline-block;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        margin-right: 6px;
    }
    .health-dot.ok { background-color: #198754; }
    .health-dot.error { background-color: #dc3545; }
    .health-dot.warn { background-color: #fd7e14; }
    .health-dot.off { background-color: #adb5bd; }

    /* Notification row */
    .notif-row {
        padding: 12px 16px;
        border-bottom: 1px solid #f0f0f0;
        transition: background 0.15s;
    }
    .notif-row:hover { background: #f8f9fa; }
    .notif-row.unread { border-left: 3px solid #0d6efd; }
    .notif-row .notif-title {
        font-weight: 600;
        color: #212529;
        margin-bottom: 2px;
    }
    .notif-row .notif-body {
        color: #6c757d;
        font-size: 0.9rem;
    }
    .notif-row .notif-meta {
        font-size: 0.78rem;
        color: #adb5bd;
        margin-top: 4px;
    }

    /* Ticker badge */
    .ticker-badge {
        display: inline-block;
        background: #e7f1ff;
        color: #0d6efd;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.78rem;
        font-weight: 600;
        margin-right: 6px;
    }

    /* Page header */
    .page-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 1.5rem;
    }

    /* Section divider */
    .section-gap { margin-top: 2rem; }

    /* Sidebar unread badge */
    .unread-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: #dc3545;
        color: white;
        font-size: 0.72rem;
        font-weight: 700;
        min-width: 20px;
        height: 20px;
        border-radius: 10px;
        padding: 0 6px;
        margin-left: 6px;
    }

    /* Filing status colours */
    .status-ingested { color: #0dcaf0; }
    .status-analyzed { color: #198754; }
    .status-dead { color: #dc3545; }

    /* Hide Streamlit default footer */
    footer { visibility: hidden; }
    </style>
    """, unsafe_allow_html=True)


def setup_auth_sidebar():
    """Render sidebar auth inputs and initialise API client / local runtime.

    Returns (use_api, client_or_none, runtime_or_none, org_id, user_id).
    """
    if "api_client" not in st.session_state:
        st.session_state.api_client = None
    if "runtime" not in st.session_state:
        st.session_state.runtime = None

    with st.sidebar:
        st.markdown("### Settings")

        # Auth context
        org_id = st.text_input("Org ID", value=st.session_state.get("org_id", GRAVITY_ORG_ID), key="sb_org_id")
        user_id = st.text_input("User ID", value=st.session_state.get("user_id", GRAVITY_USER_ID), key="sb_user_id")
        st.session_state["org_id"] = org_id
        st.session_state["user_id"] = user_id

        st.divider()

        # API mode auto-connect
        if GRAVITY_API_URL and st.session_state.api_client is None:
            from ui.api_client import GravityApiClient
            st.session_state.api_client = GravityApiClient(
                GRAVITY_API_URL,
                org_id=org_id,
                user_id=user_id,
                api_key=GRAVITY_API_KEY,
            )

        use_api = st.session_state.api_client is not None

        if use_api:
            # Keep auth headers in sync with sidebar inputs
            st.session_state.api_client.org_id = org_id
            st.session_state.api_client.user_id = user_id
            _render_connection_status()
        else:
            _render_local_mode_init()

        # Unread badge in sidebar
        st.divider()
        unread = _get_unread_count(use_api, org_id, user_id)
        if unread > 0:
            st.markdown(
                'Notifications <span class="unread-badge">%d</span>' % unread,
                unsafe_allow_html=True,
            )
        else:
            st.markdown("Notifications: 0 unread")

    return (
        use_api,
        st.session_state.api_client,
        st.session_state.runtime,
        org_id,
        user_id,
    )


def _render_connection_status():
    """Show API connection health in sidebar."""
    try:
        h = st.session_state.api_client.health()
        status = h.get("status", "unknown")
        if status == "ok":
            st.success("API connected")
        else:
            st.warning("API degraded: %s" % status)
    except Exception as exc:
        st.error("API unreachable: %s" % exc)


def _render_local_mode_init():
    """Show local runtime init controls in sidebar."""
    ticker_input = st.text_input("Tickers", value="MSFT,AAPL", key="sb_tickers")
    poll_interval = st.number_input("Poll Interval (s)", min_value=30, max_value=3600, value=300, step=30, key="sb_poll")

    if st.button("Initialize Runtime"):
        from main import build_runtime
        tickers = [t.strip().upper() for t in ticker_input.split(",") if t.strip()]
        st.session_state.runtime = build_runtime(tickers=tickers, poll_interval_seconds=int(poll_interval))
        st.success("Runtime initialized")


def _get_unread_count(use_api, org_id, user_id):
    # type: (bool, str, str) -> int
    try:
        if use_api:
            return st.session_state.api_client.count_unread_notifications()
        elif st.session_state.runtime:
            return st.session_state.runtime.state_manager.count_unread_notifications(org_id, user_id)
    except Exception:
        pass
    return 0


def require_backend(use_api, runtime):
    """Guard: stop page if no backend is configured."""
    if not use_api and runtime is None:
        st.info("Initialize runtime from the sidebar to start.")
        st.stop()


def metric_card(label, value, sub="", color=""):
    # type: (str, str, str, str) -> None
    """Render a single metric card."""
    color_class = ""
    if color:
        color_class = ' class="%s"' % color
    st.markdown(
        """<div class="metric-card">
            <h3>%s</h3>
            <div class="value"%s>%s</div>
            <div class="sub">%s</div>
        </div>""" % (label, color_class, value, sub),
        unsafe_allow_html=True,
    )


def health_dot(status):
    # type: (str) -> str
    """Return an HTML health dot span."""
    cls = "off"
    if status == "ok":
        cls = "ok"
    elif "error" in str(status):
        cls = "error"
    elif status in ("degraded", "warn"):
        cls = "warn"
    return '<span class="health-dot %s"></span>' % cls


def ticker_badge(ticker):
    # type: (str) -> str
    return '<span class="ticker-badge">%s</span>' % ticker


def format_time_ago(iso_str):
    # type: (str) -> str
    """Convert ISO timestamp to a human-readable 'time ago' string."""
    from datetime import datetime
    try:
        if "T" in iso_str:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00").replace("+00:00", ""))
        else:
            dt = datetime.fromisoformat(iso_str)
        diff = datetime.utcnow() - dt
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            m = seconds // 60
            return "%dm ago" % m
        elif seconds < 86400:
            h = seconds // 3600
            return "%dh ago" % h
        else:
            d = seconds // 86400
            return "%dd ago" % d
    except Exception:
        return iso_str
