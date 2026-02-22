# Gravity: User Journey and Product Narrative (Investor-Friendly)

## 1) What This Product Is
Gravity is an AI-powered research assistant for stock market analysts.

In simple terms:
- Companies publish important documents (earnings updates, guidance changes, risk disclosures).
- Those documents are long, technical, and easy to miss.
- Gravity watches for new filings, reads them quickly, extracts what matters, and alerts the right user.

It helps analysts move from "searching for information" to "making decisions."

## 2) Why This Product Is Needed
Today, many analysts still do this manually:
1. Monitor multiple websites for new filings.
2. Open long documents and scan for key changes.
3. Compare with prior periods.
4. Write summaries for internal teams.

Problems with this manual approach:
- Important updates can be missed or seen late.
- Analysts spend too much time reading and too little time thinking.
- Coverage does not scale well as watchlists grow.
- Teams get inconsistent outputs depending on who is on duty.

Gravity solves this by making monitoring continuous and analysis immediate.

## 3) Who Uses It

### Primary user: Public markets analyst
- Tracks a set of companies.
- Needs fast, reliable updates.
- Wants quick answers grounded in source documents.

### Secondary user: Research lead / portfolio manager
- Needs confidence that the team did not miss key filings.
- Wants concise, decision-ready summaries.

### Operational user: Product/ops engineer
- Monitors pipeline health.
- Ensures ingestion, analysis, and alerts are running reliably.

## 4) Core Value in One Sentence
Gravity reduces the time from "new filing published" to "actionable insight in analyst hands."

## 5) End-to-End User Journey (Layman View)

## Phase A: First-time onboarding (Day 1)
1. User logs in and selects their workspace/account.
2. User adds a watchlist of companies (for example: MSFT, AAPL, TSLA).
3. User starts a historical backfill (to load recent context, not just future filings).
4. Gravity processes these filings and generates notifications.
5. User sees a clean feed of relevant updates and can open each source filing.

Outcome:
- User gets immediate value in minutes, even before the next real-time filing event.

## Phase B: Daily analyst workflow
1. User opens dashboard in the morning.
2. Sees unread alerts, watchlist status, and recent filing activity.
3. Opens Notifications page and filters by ticker or alert type.
4. Marks reviewed items as read, keeps feed organized.
5. Uses Ask page to query: "What changed in guidance for company X?"
6. Receives an answer with citations, so they can verify quickly.

Outcome:
- Faster daily coverage with less manual scanning.

## Phase C: Real-time filing event workflow
1. Company releases a new SEC filing.
2. Gravity ingestion pipeline detects and pulls it.
3. AI analysis extracts key points and updates the knowledge index.
4. Matching users on that ticker receive in-app alerts.
5. Analyst opens alert, reads summary, asks follow-up questions.

Outcome:
- Team reacts faster to market-moving information.

## Phase D: Team and reliability workflow
1. Ops user opens Ops Dashboard.
2. Checks API, database, Redis, workers, queue depth, and recent failures.
3. Detects issues early (for example, backlog spike).
4. Resolves before analysts feel impact.

Outcome:
- Product trust stays high because reliability is visible and managed.

## 6) What Users Actually See
- Dashboard: "What needs my attention right now?"
- Notifications: "Show me exactly what changed."
- Watchlist: "Control what I care about."
- Ask: "Explain this filing in plain language, with proof."
- Ops Dashboard: "Is the system healthy and current?"

## 7) Problems Solved (Business Language)
- Time waste: less manual document triage.
- Missed signal risk: proactive alerts reduce blind spots.
- Scalability: one analyst can monitor more companies with confidence.
- Standardization: output quality is more consistent across team members.
- Auditability: answers are tied to source documents.

## 8) Why This Matters to Investors

### Clear pain + clear ROI
- Pain is universal in research-heavy financial workflows.
- Value is measurable: response time, coverage breadth, and analyst productivity.

### Sticky workflow
- Watchlists, history, and team habits create strong retention.
- Once integrated into daily process, replacement cost is high.

### Expansion path
- Start with in-app workflow.
- Expand to external alert channels (WhatsApp/Telegram), enterprise controls, and deeper analytics.

## 9) Simple Before vs After

Before Gravity:
- Monitor manually
- Read long filings end-to-end
- Risk missing key changes
- Slower decision cycle

After Gravity:
- Automatic monitoring
- Key points extracted immediately
- Fast, cited answers on demand
- Quicker and more confident decisions

## 10) Example Story (Concrete)
An analyst covering 40 companies starts the day with 7 new alerts.
- In 10 minutes, they know which 2 filings matter most.
- They ask 3 follow-up questions in the Ask page.
- They share a decision note before market opens.

Without Gravity, this would require opening multiple filings and manually extracting key changes, often taking much longer.

## 11) Product Positioning Statement
Gravity is the operating layer between raw regulatory filings and investment decisions: always-on monitoring, AI extraction, and explainable answers in one workflow.

## 12) Current Maturity
- Core multi-page product experience is implemented.
- Multi-tenant user scoping and notification workflow are in place.
- Backfill + proactive monitoring flows are live.
- Ops visibility exists for health and pipeline monitoring.

## 13) What Comes Next (Near-term Product Roadmap)
1. Notification preference controls (reduce noise further).
2. Better backfill job status tracking in UI.
3. Enhanced ops observability and replay tools.
4. External notification channel integration.

---

This document is intentionally non-technical and suitable for demos, investor conversations, and stakeholder onboarding.

