"""Watchlist & Backfill -- manage watched tickers and trigger historical data loads."""

import streamlit as st

from ui.components import (
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
st.markdown("# Watchlist & Backfill")
st.caption("Manage the tickers you monitor and load historical filings")

if use_api:
    try:
        available_markets = client.list_markets() or ["US_SEC"]
    except Exception:
        available_markets = ["US_SEC"]
else:
    provider = runtime.graph_runtime.ingestion_nodes.edgar_client
    available_markets = [getattr(provider, "market_code", "US_SEC")]

selected_market = st.selectbox(
    "Market",
    options=available_markets,
    index=0,
    key="wl_market_select",
)
selected_exchange = st.text_input(
    "Exchange (optional)",
    value="NSE" if selected_market == "IN_NSE" else ("BSE" if selected_market == "IN_BSE" else ""),
    key="wl_exchange_input",
)

# ---------------------------------------------------------------------------
# Current watchlist
# ---------------------------------------------------------------------------
try:
    if use_api:
        watchlist = client.list_watchlist_market(market=selected_market)
    else:
        watchlist = runtime.state_manager.list_watchlist(org_id, user_id, market=selected_market)
except Exception as exc:
    st.error("Failed to load watchlist: %s" % exc)
    watchlist = []

st.markdown("### Your Watchlist")

if watchlist:
    # Display as a row of badges
    badges = " ".join(
        "%s <small>(%s)</small>" % (ticker_badge(w.get("ticker", "")), w.get("market", "US_SEC")) for w in watchlist
    )
    st.markdown(badges, unsafe_allow_html=True)
    st.caption("%d ticker%s watched" % (len(watchlist), "s" if len(watchlist) != 1 else ""))
else:
    st.info("Your watchlist is empty. Add tickers below to start receiving filing alerts.")

# ---------------------------------------------------------------------------
# Add / Remove tickers
# ---------------------------------------------------------------------------
st.markdown("### Manage Tickers")

add_col, remove_col = st.columns(2)

with add_col:
    st.markdown("**Add tickers**")
    add_input = st.text_input(
        "Tickers to add",
        value="",
        placeholder="MSFT, AAPL, GOOG",
        key="wl_add",
        label_visibility="collapsed",
    )
    if st.button("Add to watchlist", type="primary", use_container_width=True, key="wl_add_btn"):
        tickers = [t.strip().upper() for t in add_input.split(",") if t.strip()]
        if not tickers:
            st.warning("Enter at least one ticker.")
        else:
            try:
                if use_api:
                    client.add_watchlist_market(tickers=tickers, market=selected_market, exchange=selected_exchange)
                else:
                    for t in tickers:
                        runtime.state_manager.add_watchlist_ticker(
                            org_id,
                            user_id,
                            t,
                            market=selected_market,
                            exchange=selected_exchange,
                        )
                st.success("Added: %s" % ", ".join(tickers))
                st.rerun()
            except Exception as exc:
                st.error("Failed: %s" % exc)

    resolve_symbol = st.text_input("Resolve symbol", value="", placeholder="e.g. RELIANCE", key="wl_resolve_symbol")
    if st.button("Resolve instrument", use_container_width=True, key="wl_resolve_btn"):
        symbol = resolve_symbol.strip().upper()
        if not symbol:
            st.warning("Enter a symbol to resolve.")
        else:
            try:
                if use_api:
                    resolved = client.resolve_instrument(symbol, market=selected_market)
                else:
                    provider = runtime.graph_runtime.ingestion_nodes.edgar_client
                    resolver = getattr(provider, "resolve_instrument", None)
                    resolved = resolver(symbol) if callable(resolver) else {"ticker": symbol, "issuer_id": "", "exchange": ""}
                    resolved["market"] = selected_market
                st.caption(
                    "Resolved: ticker=%s, issuer_id=%s, exchange=%s"
                    % (
                        resolved.get("ticker", symbol),
                        resolved.get("issuer_id", "") or "N/A",
                        resolved.get("exchange", "") or "N/A",
                    )
                )
            except Exception as exc:
                st.error("Resolve failed: %s" % exc)

with remove_col:
    st.markdown("**Remove tickers**")
    if watchlist:
        watched_tickers = [
            "%s (%s)" % (w.get("ticker", ""), w.get("exchange") or w.get("market", "US_SEC")) for w in watchlist
        ]
        remove_selection = st.multiselect(
            "Select tickers to remove",
            options=watched_tickers,
            key="wl_remove",
            label_visibility="collapsed",
        )
        if st.button("Remove selected", type="secondary", use_container_width=True, key="wl_remove_btn"):
            if not remove_selection:
                st.warning("Select tickers to remove.")
            else:
                try:
                    remove_tickers = [item.split(" (", 1)[0].strip().upper() for item in remove_selection]
                    if use_api:
                        client.remove_watchlist_market(
                            tickers=remove_tickers,
                            market=selected_market,
                            exchange=selected_exchange,
                        )
                    else:
                        for t in remove_tickers:
                            runtime.state_manager.remove_watchlist_ticker(
                                org_id,
                                user_id,
                                t,
                                market=selected_market,
                                exchange=selected_exchange,
                            )
                    st.success("Removed: %s" % ", ".join(remove_tickers))
                    st.rerun()
                except Exception as exc:
                    st.error("Failed: %s" % exc)
    else:
        st.caption("No tickers to remove.")

st.divider()

# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------
st.markdown("### Historical Backfill")
st.caption("Load and analyze historical SEC filings for your watchlist tickers.")

bf_col1, bf_col2 = st.columns([2, 1])

with bf_col1:
    # Default to current watchlist tickers
    default_tickers = ", ".join(w.get("ticker", "") for w in watchlist) if watchlist else "MSFT"
    bf_tickers = st.text_input(
        "Tickers to backfill",
        value=default_tickers,
        key="bf_tickers",
    )

with bf_col2:
    bf_limit = st.number_input(
        "Filings per ticker",
        min_value=1,
        max_value=50,
        value=8,
        step=1,
        key="bf_limit",
    )

opt_col1, opt_col2 = st.columns(2)
with opt_col1:
    bf_include_existing = st.checkbox("Include already-processed filings", value=False, key="bf_existing")
with opt_col2:
    bf_notify = st.checkbox("Send notifications for backfill results", value=True, key="bf_notify")

if st.button("Start Backfill", type="primary", use_container_width=True, key="bf_start"):
    tickers = [t.strip().upper() for t in bf_tickers.split(",") if t.strip()]
    if not tickers:
        st.warning("Enter at least one ticker.")
    else:
        with st.spinner("Running backfill for %s..." % ", ".join(tickers)):
            try:
                if use_api:
                    result = client.backfill_market(
                        tickers=tickers,
                        market=selected_market,
                        exchange=selected_exchange,
                        per_ticker_limit=int(bf_limit),
                        include_existing=bf_include_existing,
                        notify=bf_notify,
                    )
                    mode = result.get("mode", "unknown")
                    if mode == "async":
                        st.success("Backfill job submitted (async). Job ID: %s" % result.get("job_id", "?"))
                        st.info("Results will appear in your notifications once processing completes.")
                    else:
                        st.success(
                            "Backfill complete: %s filings processed, %s analyzed, %s indexed"
                            % (
                                result.get("filings_processed", 0),
                                result.get("analyzed", 0),
                                result.get("indexed", 0),
                            )
                        )
                else:
                    from services.backfill import run_backfill

                    payload = {
                        "tickers": tickers,
                        "market": selected_market,
                        "exchange": selected_exchange,
                        "per_ticker_limit": int(bf_limit),
                        "include_existing": bf_include_existing,
                        "notify": bf_notify,
                        "org_id": org_id,
                    }
                    result = run_backfill(runtime, runtime.state_manager, payload)
                    st.success(
                        "Backfill complete: %s filings, %s analyzed, %s indexed"
                        % (result["filings_processed"], result["analyzed"], result["indexed"])
                    )
            except Exception as exc:
                st.error("Backfill failed: %s" % exc)

# ---------------------------------------------------------------------------
# Ingestion trigger
# ---------------------------------------------------------------------------
st.divider()
st.markdown("### Run Ingestion Cycle")
st.caption("Check SEC EDGAR for the latest filings matching your watchlist.")

ing_tickers = st.text_input(
    "Tickers to ingest",
    value=default_tickers if watchlist else "MSFT,AAPL",
    key="ing_tickers",
)

if st.button("Run Ingestion", use_container_width=True, key="ing_start"):
    tickers = [t.strip().upper() for t in ing_tickers.split(",") if t.strip()]
    if not tickers:
        st.warning("Enter at least one ticker.")
    else:
        with st.spinner("Running ingestion for %s..." % ", ".join(tickers)):
            try:
                if use_api:
                    result = client.ingest_market(tickers=tickers, market=selected_market, exchange=selected_exchange)
                    mode = result.get("mode", "unknown")
                    if mode == "async":
                        st.success("Ingestion job submitted. Job ID: %s" % result.get("job_id", "?"))
                    else:
                        st.success("Processed %s filings" % result.get("filings_processed", 0))
                else:
                    payloads = runtime.graph_runtime.run_ingestion_cycle(
                        tickers=tickers,
                        market=selected_market,
                        exchange=selected_exchange,
                    )
                    for payload in payloads:
                        analysis = runtime.graph_runtime.analyze_filing(payload)
                        if analysis:
                            runtime.graph_runtime.index_analysis(analysis)
                    st.success("Cycle complete. Processed %d new filings." % len(payloads))
            except Exception as exc:
                st.error("Ingestion failed: %s" % exc)
