"""Notification Center -- full notification management with filters and bulk actions."""

import streamlit as st

from ui.components import (
    format_time_ago,
    inject_css,
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
st.markdown("# Notifications")

# Unread count
try:
    if use_api:
        unread_count = client.count_unread_notifications()
    else:
        unread_count = runtime.state_manager.count_unread_notifications(org_id, user_id)
except Exception:
    unread_count = 0

if unread_count > 0:
    st.caption("%d unread notification%s" % (unread_count, "s" if unread_count != 1 else ""))
else:
    st.caption("All caught up")

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([1, 1, 1, 1])

with filter_col1:
    unread_only = st.checkbox("Unread only", value=True, key="notif_unread")
with filter_col2:
    ticker_filter = st.text_input("Filter by ticker", value="", key="notif_ticker", placeholder="e.g. MSFT")
with filter_col3:
    type_filter = st.selectbox(
        "Notification type",
        options=["All", "FILING_FOUND"],
        index=0,
        key="notif_type",
    )
with filter_col4:
    page_size = st.selectbox("Show", options=[25, 50, 100], index=1, key="notif_limit")

# ---------------------------------------------------------------------------
# Bulk actions
# ---------------------------------------------------------------------------
action_col1, action_col2, _ = st.columns([1, 1, 3])

with action_col1:
    if st.button("Mark all read", type="secondary", use_container_width=True):
        try:
            t = ticker_filter.strip().upper() or None
            nt = type_filter if type_filter != "All" else None
            if use_api:
                result = client.read_all_notifications(ticker=t, notification_type=nt)
                count = result.get("updated", 0)
            else:
                count = runtime.state_manager.mark_all_notifications_read(
                    org_id, user_id, ticker=t, notification_type=nt
                )
            st.toast("Marked %d notifications as read" % count)
            st.rerun()
        except Exception as exc:
            st.error("Failed: %s" % exc)

with action_col2:
    if st.button("Refresh", use_container_width=True):
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Notification list
# ---------------------------------------------------------------------------
try:
    if use_api:
        notifications = client.list_notifications(
            limit=int(page_size),
            unread_only=unread_only,
            ticker=ticker_filter.strip().upper() or None,
            notification_type=type_filter if type_filter != "All" else None,
        )
    else:
        notifications = runtime.state_manager.list_notifications(
            org_id,
            user_id,
            limit=int(page_size),
            unread_only=unread_only,
            ticker=ticker_filter.strip().upper() or None,
            notification_type=type_filter if type_filter != "All" else None,
        )
except Exception as exc:
    st.error("Failed to load notifications: %s" % exc)
    notifications = []

if not notifications:
    st.info("No notifications match your filters.")
    st.stop()

# Render each notification as an expandable card
for notif in notifications:
    is_unread = not notif.get("is_read", True)
    nid = notif.get("id", 0)
    badge = ticker_badge(notif.get("ticker", ""))
    time_str = format_time_ago(notif.get("created_at", ""))
    unread_marker = " :blue[NEW]" if is_unread else ""

    header = "%s  %s%s  --  %s" % (
        notif.get("ticker", ""),
        notif.get("title", "Untitled"),
        unread_marker,
        time_str,
    )

    with st.expander(header, expanded=is_unread):
        st.markdown(
            "%s **%s**" % (badge, notif.get("title", "")),
            unsafe_allow_html=True,
        )
        st.write(notif.get("body", ""))

        detail_col1, detail_col2, detail_col3 = st.columns(3)
        with detail_col1:
            st.caption("Type: %s" % notif.get("notification_type", ""))
        with detail_col2:
            st.caption("Accession: %s" % notif.get("accession_number", ""))
        with detail_col3:
            st.caption("Created: %s" % notif.get("created_at", ""))

        if is_unread:
            if st.button("Mark as read", key="mark_%d" % nid):
                try:
                    if use_api:
                        client.mark_notification_read(nid)
                    else:
                        runtime.state_manager.mark_notification_read(org_id, user_id, nid)
                    st.toast("Notification marked as read")
                    st.rerun()
                except Exception as exc:
                    st.error("Failed: %s" % exc)
