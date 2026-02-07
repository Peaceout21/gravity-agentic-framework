# Architectural Blueprint: The Gravity Agentic Framework

> **Context**: This document serves as the authoritative source of truth for refactoring `gravitic-celestial` from a monolithic script into a multi-agent autonomous swarm. It is designed to be consumed by an LLM to generate the complete codebase.

## 1. Problem Statement: Why We Are Pivoting

### 1.1 The "Fragile Monolith" Problem
The current system operates as a linear procedural script (`run_poller.py`). While it successfully fetches data, it lacks **cognitive resilience**.
-   **No Agency**: If the SEC website changes its HTML structure or returns a "Rate Limit" error, the script simply crashes or logs an error. It cannot "think" to pause and retry, or switch to a mirror source.
-   **The "Empty Extraction" Failure**: We observed cases where the system extracted only the cover page of an 8-K. A human analyst would immediately notice "Wait, where is the revenue?" and look for an attachment (Exhibit 99.1). The current script blindly indexes the empty data, polluting the search engine.
-   **Context Amnesia**: The system handles each filing in isolation. It cannot remember that "Microsoft usually releases guidance in the conference call, not the 8-K" and thus fails to look for alternative documents when guidance is missing.

### 1.2 The Goal
We need a system that behaves like a **team of human analysts**, not a script. It must:
1.  **Self-Correct**: "I didn't find the revenue table. Let me check the attachments."
2.  **Persist Context**: "This is Q3. How does it compare to Q2?"
3.  **Synthesize**: "Combine the SEC filing with the Polymarket sentiment."

## 2. Integrated Data Sources

The Agentic Framework will continuously monitor and fuse data from the following high-value sources:

| Source | Role | Access Method | Agent Responsibility |
| :--- | :--- | :--- | :--- |
| **SEC EDGAR** | **Primary Truth**. 8-K, 10-Q, 10-K filings containing GAAP financials. | `EdgarClient` (Wrapper around `edgartools`) | **Ingestion Agent** |
| **Polymarket** | **Sentiment Signal**. Prediction market odds (e.g., "Will MSFT revenue exceed $50B?"). | `PolymarketClient` API | **Ingestion Agent** |
| **News / Social** | **Context**. Breaking news that explains stock moves (e.g., "CEO Resigns"). | `Firecrawl` (Web Scraper) / RSS | **Ingestion Agent** |

## 3. The Agentic Solution: How It Works

We solve the "Fragile Monolith" problem by decomposing the system into specialized, autonomous agents.

### 3.1 Why Agents?
-   **vs. Scripts**: Agents have loops and state. They can *retry* a task with a different strategy (e.g., "Gemini 3 failed, let me try a simpler prompt").
-   **Tool Use**: Agents can "decide" which tool to use. If a user asks about "Sentiment," the Synthesis Agent knows to query the *Polymarket* index, not just the SEC index.

### 3.2 The Swarm Architecture

#### 🕵️ Agent 1: Ingestion ("The Hunter")
-   **Problem Solved**: "Data requires constant monitoring and validation."
-   **Tools**: `EdgarClient`, `MarketRegistry`, `PolymarketClient`.
-   **Workflow**:
    1.  Monitors data sources (EDGAR, Polymarket).
    2.  **Validation**: Checks if downloaded text > 1000 chars. If not, hunts for 'Exhibit 99.1'.
    3.  **Handoff**: Pushes a "Raw Data Event" to the Analyst.

#### 🧠 Agent 2: Analyst ("The Brain")
-   **Problem Solved**: "Raw text is noisy; we need structured signal."
-   **Tools**: `ExtractionEngine` (**Gemini 3 Flash**).
-   **Workflow**:
    1.  Receives raw text.
    2.  **Reasoning**: "I need Revenue and EPS. If I see 'Non-GAAP', I must note the adjustment."
    3.  **Output**: Produces a structured `EarningsReport` JSON.

#### 📚 Agent 3: Knowledge ("The Librarian")
-   **Problem Solved**: "We need to remember everything for RAG."
-   **Tools**: `HybridRAGEngine` (ChromaDB + BM25).
-   **Workflow**:
    1.  Indexes structured reports.
    2.  **Retrieval**: Performs semantic search ("Cloud growth") and keyword search ("$46.7B") to find exact matches.

#### 🎓 Agent 4: Synthesis ("The Orchestrator")
-   **Problem Solved**: "Users ask complex questions requiring synthesis."
-   **Tools**: `KnowledgeAgent.query()`.
-   **Workflow**:
    1.  User asks: "Why is the stock down despite beating revenue?"
    2.  **Plan**: "Query SEC for Revenue (Beat?). Query Polymarket/News for 'Stock Down' reason."
    3.  **Synthesis**: "Revenue beat by 5%, BUT Polymarket shows 80% odds of 'Guidance Miss'."

---

## 2. Technical Specification

### 2.1 Directory Structure
The new `core/` structure must be implemented exactly as follows:

```text
gravitic-celestial/
├── core/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base_agent.py          # Abstract Base Class
│   │   ├── ingestion_agent.py     # Monitors EDGAR/News
│   │   ├── analyst_agent.py       # Extracts Insights (Gemini 3)
│   │   ├── knowledge_agent.py     # Manages RAG/Chroma
│   │   └── synthesis_agent.py     # Handles User Queries
│   ├── framework/
│   │   ├── __init__.py
│   │   ├── event_bus.py           # Pub/Sub System
│   │   ├── messages.py            # Pydantic Data Models
│   │   └── state_manager.py       # Distributed State Tracking
│   ├── tools/
│   │   ├── edgar_client.py        # Existing (Refined)
│   │   ├── extraction_engine.py   # Existing (Refined)
│   │   └── hybrid_rag.py          # Existing (Refined)
├── ui/
│   ├── app.py                     # Streamlit Dashboard
│   └── components/                # UI Widgets
└── main.py                        # Entry Point (Agent Orchestrator)
```

### 2.2 Core Interfaces (Python Definitions)

#### 2.2.1 Data Models (`core/framework/messages.py`)
```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

class AgentMessage(BaseModel):
    id: str = Field(..., description="Unique Message ID")
    source: str = Field(..., description="Agent Name")
    topic: str = Field(..., description="Event Topic (e.g., 'FILING_FOUND')")
    payload: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class FilingPayload(BaseModel):
    ticker: str
    accession_number: str
    filing_url: str
    raw_text: str  # Full markdown content including Exhibit 99.1
    metadata: Dict[str, Any]

class AnalysisPayload(BaseModel):
    ticker: str
    accession_number: str
    kpis: List[Dict[str, str]]
    summary: Dict[str, List[str]]
    guidance: List[Dict[str, str]]
```

#### 2.2.2 Base Agent (`core/agents/base_agent.py`)
```python
from abc import ABC, abstractmethod
from core.framework.event_bus import EventBus
from core.framework.messages import AgentMessage

class BaseAgent(ABC):
    def __init__(self, name: str, event_bus: EventBus):
        self.name = name
        self.bus = event_bus
        self.running = False
        self._setup()

    def _setup(self):
        """Register listeners here."""
        pass

    @abstractmethod
    def start(self):
        """Main execution loop."""
        pass

    @abstractmethod
    def handle_message(self, message: AgentMessage):
        """Process incoming events."""
        pass

    def publish(self, topic: str, payload: dict):
        msg = AgentMessage(
            id=generate_uuid(),
            source=self.name,
            topic=topic,
            payload=payload
        )
        self.bus.publish(msg)
```

---

## 3. Agent Specifications

### 3.1 🕵️ Ingestion Agent (`ingestion_agent.py`)
**Goal**: Ensure 100% capture of relevant data.
**Logic Flow**:
1.  **Loop**: Wakes up every `n` minutes.
2.  **Scan**: Calls `EdgarClient.get_latest_filings(tickers)`.
3.  **Filter**: Checks `StateManager` (SQLite) to see if `accession_number` exists.
4.  **Fetch**: If new, calls `EdgarClient.get_filing_text`.
    -   *Critical Logic*: Must verify that the text length > 1000 chars. If shorter, explicitly hunt for 'EX-99.1'.
5.  **Publish**: Emits `FILING_FOUND` event with the `FilingPayload`.
6.  **Persist**: Marks filing as "INGESTED" in StateManager.

### 3.2 🧠 Analyst Agent (`analyst_agent.py`)
**Goal**: Extract high-fidelity financial signal.
**Model Config**:
-   **Model**: `gemini-3-flash-preview`
-   **Temperature**: `0.1` (Strict adherence to facts)
-   **System Prompt**: "You are a CFA-level financial analyst. You strictly output JSON. You prioritize GAAP numbers but note Non-GAAP adjustments."
**Logic Flow**:
1.  **Listen**: Subscribes to `FILING_FOUND`.
2.  **Process**:
    -   Receive `FilingPayload`.
    -   Construct Prompt: "Extract Revenue, EPS, Guidance from this text: {raw_text}".
    -   Call `ExtractionEngine` (Gemini 3).
    -   *Self-Correction*: If JSON is empty or missing key fields ("Revenue"), perform a reflection step: "Data missing. Is the input text truncated? Log warning."
3.  **Publish**: Emits `ANALYSIS_COMPLETED` with `AnalysisPayload`.

### 3.3 📚 Knowledge Agent (`knowledge_agent.py`)
**Goal**: Persistent Memory.
**Logic Flow**:
1.  **Listen**: Subscribes to `ANALYSIS_COMPLETED`.
2.  **Chunk & Embed**:
    -   KPIs -> "Metric Cards" (small chunks).
    -   Summaries -> "Narrative Blocks" (larger chunks).
3.  **Index**: Pushes to `HybridRAGEngine` (ChromaDB + BM25).
4.  **Query Handle**: Exposes a `query(text)` method invoked by the Synthesis Agent.

### 3.4 🎓 Synthesis Agent (`synthesis_agent.py`)
**Goal**: User Interaction.
**Logic Flow**:
1.  **Input**: Receives user question from Dashboard (via direct method call or event).
2.  **Retrieval**: Calls `KnowledgeAgent.query("Microsoft cloud revenue")`.
3.  **Reasoning**: Uses Gemini 3 to synthesize the retrieved chunks into a coherent Markdown answer.
4.  **Output**: Returns final response to UI.

---

## 4. Implementation Steps (Execution Order)

1.  **Framework Core**: Implement `event_bus.py`, `messages.py`, and `base_agent.py`.
2.  **Ingestion**: Implement `IngestionAgent` using the existing (but wrapped) `EdgarClient`.
3.  **Analyst**: Implement `AnalystAgent` wrapping `ExtractionEngine`. **Upgrade extraction to Gemini 3.**
4.  **Knowledge**: Implement `KnowledgeAgent` wrapping `HybridRAGEngine`.
5.  **Orchestration**: Create `main.py` to instantiate the bus and agents, and start them in separate threads.
6.  **UI**: Update Streamlit to poll the Synthesis Agent.

## 5. Developer Notes & Context Handoff

> **⚠️ CRITICAL CONTEXT FOR THE NEXT AGENT**
> Read this section before writing a single line of code. These are "blood-written rules" learned from previous failures.

### 5.1 Dependency Mines
-   **`edgartools` & `hishel`**: We MUST pin `hishel==0.0.30`. Newer versions break the EDGAR client. Do not upgrade blindly.
-   **`graphviz`**: The `ContagionGraph` feature requires a *system-level* install (`brew install graphviz`). If not present, the `KnowledgeAgent` should degrade gracefully (disable graph features) rather than crashing.
-   **Python 3.9**: The environment is strictly Python 3.9. Avoid syntax newer than 3.9 (e.g., `str | None` type hints might fail in some runtime contexts; prefer `Optional[str]`).

### 5.2 RAG & Ranking Quirks
-   **ChromaDB Order**: ChromaDB does **NOT** return documents in relevance order when fetching by ID. You CANNOT rely on the returned list order.
    -   *Solution*: The `KnowledgeAgent` must implement **Reciprocal Rank Fusion (RRF)** manually in Python after fetching results from Vector and BM25 stores.
-   **BM25 Persistence**: `rank_bm25` is in-memory only. You must rebuild the index from the database on Agent startup (`_load_bm25_index`).

### 5.3 Extraction Nuances
-   **Exhibit 99.1 is King**: For 8-K Earnings filings, the "Cover Page" is useless legal boilerplate. The actual numbers are *always* in **Exhibit 99.1** (Press Release).
    -   *Rule*: The `IngestionAgent` must explicitly scan attachments for "99.1" or "Press Release" and append that text to the main body.
-   **Gemini 3 Flash**: We are switching to `gemini-3-flash-preview`. This model is significantly faster but check the API docs for the latest `google-genai` (vs `google.generativeai`) SDK compatibility.

### 5.4 Environment Variables
Ensure these are present in `.env`:
-   `GOOGLE_API_KEY`: Required for Analyst/Synthesis agents.
-   `FIRE_CRAWL_API_KEY`: Required for Ingestion agent (News).
-   `SEC_IDENTITY`: Required for accessing EDGAR (format: `Name email@domain.com`).
