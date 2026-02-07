# Gravity Agentic Framework (LangGraph)

Hybrid agentic framework using LangGraph for orchestration, LangChain-compatible tooling, SQLite checkpoints, and hybrid retrieval.

## Quickstart

1. Create and activate a Python 3.9 environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Configure environment variables:
   ```bash
   cp .env.example .env
   ```
4. Run one pipeline cycle:
   ```bash
   python main.py --tickers MSFT,AAPL --run-once
   ```
5. Run Streamlit UI:
   ```bash
   streamlit run ui/app.py
   ```

## Architecture

- `core/graph/`: LangGraph state, nodes, builder, checkpointing.
- `core/framework/`: Event bus, message contracts, processing state manager.
- `core/tools/`: EDGAR adapter, extraction/synthesis adapters, hybrid RAG utilities.
- `core/agents/`: Agent wrappers around graph workflows.
- `main.py`: Runtime composition and polling thread.

## Notes

- Python 3.9-safe syntax only.
- `hishel==0.0.30` is pinned for EDGAR compatibility.
- `graphviz` is optional and not required for startup.
