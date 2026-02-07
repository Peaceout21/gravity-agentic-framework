# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Gravity Agentic Framework — a 4-agent autonomous swarm for extracting, analyzing, and synthesizing SEC financial filings. Built on LangGraph for workflow orchestration, ChromaDB + BM25 for hybrid retrieval, and Gemini for LLM extraction/synthesis. The main application lives in `gravitic-celestial/`.

## Commands

All commands run from `gravitic-celestial/`.

```bash
# Install dependencies
pip install -r requirements.txt

# Run one pipeline cycle (ingestion → analysis → indexing)
python main.py --tickers MSFT,AAPL --run-once

# Run continuous polling mode
python main.py --tickers MSFT,AAPL --poll-interval 300

# Run Streamlit UI
streamlit run ui/app.py

# Run all tests
python -m unittest discover tests/

# Run a single test file
python -m unittest tests/test_rrf.py
```

## Environment Variables

Configured via `gravitic-celestial/.env` (see `.env.example`):
- `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) — Gemini LLM for extraction/synthesis
- `FIRECRAWL_API_KEY` — web scraping for news sources
- `SEC_IDENTITY` — required SEC EDGAR header, format: `"Name email@domain.com"`

## Architecture

### Agent Pipeline

Four agents form a sequential pipeline, communicating via an in-process threaded EventBus (`core/framework/event_bus.py`) with topics `FILING_FOUND`, `ANALYSIS_COMPLETED`, `USER_QUERY`, `SYNTHESIS_COMPLETED`, and `DEAD_LETTER`:

1. **Ingestion Agent** — polls SEC EDGAR for new filings, deduplicates by accession number against SQLite state, fetches full text, hunts Exhibit 99.1 for 8-K filings when main text is too short (<1000 chars)
2. **Analyst Agent** — sends filing text to Gemini for structured JSON extraction (revenue, EPS, guidance). Validates output; on failure, does one reflection retry, then dead-letters
3. **Knowledge Agent** — chunks KPIs as "Metric Cards" and summaries as "Narrative Blocks", indexes to ChromaDB, rebuilds in-memory BM25 index
4. **Synthesis Agent** — on-demand user queries: retrieves via dual semantic + keyword search, fuses results with Reciprocal Rank Fusion (RRF), generates cited markdown answers

### LangGraph Workflows

Each agent's logic is implemented as a compiled LangGraph `StateGraph` in `core/graph/builder.py`. The `GraphRuntime` class builds and owns four graphs:
- **Ingestion graph**: poll → dedupe → fetch text → conditional exhibit fetch → emit payload
- **Analysis graph**: build prompt → call Gemini → validate JSON → (reflect retry | dead letter | emit)
- **Knowledge graph**: chunk → index ChromaDB → update BM25 → persist receipt
- **Query graph**: parse question → semantic retrieval → keyword retrieval → RRF fuse → synthesize

Graph nodes live in `core/graph/nodes/`. Graph state is checkpointed to `data/checkpoints.db` via `core/graph/checkpoint.py`.

### Key Layers

- `core/agents/` — agent wrappers that subscribe to EventBus topics and delegate to GraphRuntime
- `core/framework/` — EventBus (pub/sub with retry), Pydantic message models (`messages.py`), SQLite state manager tracking filing status (`INGESTED` → `ANALYZED` → `ANALYZED_NOT_INDEXED` → `DEAD_LETTER`)
- `core/graph/` — LangGraph state definition, graph builder, checkpoint store, node implementations
- `core/tools/` — `EdgarClient` (SEC API wrapper), `ExtractionEngine`/`SynthesisEngine` (Gemini adapters), `HybridRAGEngine` (ChromaDB + BM25 with RRF fusion)
- `main.py` — `FrameworkRuntime` composes all components; `run_pipeline_once()` for single-cycle, `start()` for continuous polling via daemon thread

### Data Storage

All in `gravitic-celestial/data/`:
- `state.db` — filing processing status (deduplication by accession number)
- `rag.db` — RAG chunks for BM25/keyword search
- `checkpoints.db` — LangGraph execution state

## Critical Constraints

- **Python 3.9 syntax only** — use `Optional[str]` not `str | None`, avoid 3.10+ features
- **`hishel==0.0.30` is pinned** — newer versions break the EDGAR client; do not upgrade
- **ChromaDB does not return results in relevance order** — always use RRF fusion after retrieval, never rely on raw ChromaDB result ordering
- **BM25 is in-memory only** — the `rank_bm25` index must be rebuilt from the database on every startup (`_load_bm25_index`)
- **Exhibit 99.1 is essential for 8-K filings** — the cover page is legal boilerplate; actual earnings data is in the exhibit attachment. The ingestion pipeline must scan for "99.1" or "Press Release"
- **`graphviz` is optional** — used for ContagionGraph visualization; system should degrade gracefully if not installed
