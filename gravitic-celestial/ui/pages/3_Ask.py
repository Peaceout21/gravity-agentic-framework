"""Ask -- Dedicated Q&A interface for filing analysis."""

import streamlit as st

from ui.components import inject_css, require_backend, setup_auth_sidebar, ticker_badge

inject_css()

use_api, client, runtime, org_id, user_id = setup_auth_sidebar()
require_backend(use_api, runtime)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown("# Ask about Filings")
st.caption("Get AI-powered answers with citations from analyzed SEC filings")

# ---------------------------------------------------------------------------
# Chat-style Q&A
# ---------------------------------------------------------------------------

# Maintain conversation history in session state
if "qa_history" not in st.session_state:
    st.session_state.qa_history = []

# Input area
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
        if st.form_submit_button("Clear history", use_container_width=True):
            st.session_state.qa_history = []

if submit and question.strip():
    with st.spinner("Analyzing filings..."):
        try:
            if use_api:
                result = client.query(question.strip(), ticker=ticker_context.strip() or None)
                answer_md = result.get("answer_markdown", "No answer generated.")
                citations = result.get("citations", [])
            else:
                answer = runtime.synthesis_agent.answer(question.strip())
                answer_md = answer.answer_markdown
                citations = answer.citations

            st.session_state.qa_history.append({
                "question": question.strip(),
                "ticker": ticker_context.strip().upper() if ticker_context.strip() else None,
                "answer": answer_md,
                "citations": citations,
            })
        except Exception as exc:
            st.session_state.qa_history.append({
                "question": question.strip(),
                "ticker": ticker_context.strip().upper() if ticker_context.strip() else None,
                "answer": "Error: %s" % exc,
                "citations": [],
            })

# ---------------------------------------------------------------------------
# Display conversation
# ---------------------------------------------------------------------------
if not st.session_state.qa_history:
    st.markdown("---")
    st.markdown("### Getting started")
    st.markdown("""
    **Example questions you can ask:**
    - What was Microsoft's revenue last quarter?
    - How did Apple's gross margin compare year-over-year?
    - Summarize the key guidance from the latest GOOG earnings
    - What risks did Tesla highlight in their most recent 10-K?

    **Tips:**
    - Use the ticker context field to narrow results to a specific company
    - Questions work best when filings have been ingested and analyzed first
    - Answers include citations linking back to source filings
    """)
else:
    for i, entry in enumerate(reversed(st.session_state.qa_history)):
        idx = len(st.session_state.qa_history) - i

        # Question
        q_header = "**Q%d:** %s" % (idx, entry["question"])
        if entry.get("ticker"):
            q_header = "%s %s" % (ticker_badge(entry["ticker"]), q_header)
        st.markdown(q_header, unsafe_allow_html=True)

        # Answer
        st.markdown(entry["answer"])

        # Citations
        if entry.get("citations"):
            st.caption("Sources: %s" % ", ".join(entry["citations"]))

        st.divider()
