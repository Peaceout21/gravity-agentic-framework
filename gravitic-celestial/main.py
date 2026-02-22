"""Entry point for the LangGraph-based agentic framework."""

import argparse
import os
import threading
import time

from dotenv import load_dotenv

from core.agents.analyst_agent import AnalystAgent
from core.agents.ingestion_agent import IngestionAgent
from core.agents.knowledge_agent import KnowledgeAgent
from core.agents.synthesis_agent import SynthesisAgent
from core.adapters.factory import create_backends
from core.framework.event_bus import EventBus
from core.graph.builder import GraphRuntime
from core.tools.extraction_engine import ExtractionEngine, GeminiAdapter, SynthesisEngine
from core.tools.provider_factory import create_market_provider


class FrameworkRuntime(object):
    def __init__(self, tickers, poll_interval_seconds=300, market=None):
        load_dotenv()

        sec_identity = os.getenv("SEC_IDENTITY", "Unknown unknown@example.com")
        default_market = market or (os.getenv("GRAVITY_MARKET_DEFAULT", "US_SEC") or "US_SEC").strip().upper()
        self.market = default_market
        gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        gemini_model = os.getenv("GEMINI_MODEL")

        # Select backends based on DATABASE_URL / REDIS_URL env vars
        backends = create_backends()

        self.event_bus = EventBus()
        self.state_manager = backends["state_manager"]
        self.edgar_client = create_market_provider(market=self.market, sec_identity=sec_identity)
        self.extraction_engine = ExtractionEngine(adapter=GeminiAdapter(api_key=gemini_api_key, model_name=gemini_model))
        self.synthesis_engine = SynthesisEngine(adapter=GeminiAdapter(api_key=gemini_api_key, model_name=gemini_model))
        self.rag_engine = backends["rag_engine"]
        self.checkpoint_store = backends["checkpoint_store"]

        self.graph_runtime = GraphRuntime(
            state_manager=self.state_manager,
            edgar_client=self.edgar_client,
            extraction_engine=self.extraction_engine,
            rag_engine=self.rag_engine,
            synthesis_engine=self.synthesis_engine,
            tickers=tickers,
            checkpoint_store=self.checkpoint_store,
        )

        self.ingestion_agent = IngestionAgent(
            event_bus=self.event_bus,
            graph_runtime=self.graph_runtime,
            tickers=tickers,
            poll_interval_seconds=poll_interval_seconds,
            market=self.market,
        )
        self.analyst_agent = AnalystAgent(event_bus=self.event_bus, graph_runtime=self.graph_runtime)
        self.knowledge_agent = KnowledgeAgent(event_bus=self.event_bus, graph_runtime=self.graph_runtime)
        self.synthesis_agent = SynthesisAgent(event_bus=self.event_bus, graph_runtime=self.graph_runtime)

        self._poll_thread = None

    def start(self):
        self.event_bus.start()
        self.analyst_agent.start()
        self.knowledge_agent.start()
        self.synthesis_agent.start()

        self._poll_thread = threading.Thread(target=self.ingestion_agent.start, daemon=True, name="ingestion-poller")
        self._poll_thread.start()

    def stop(self):
        self.ingestion_agent.running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=2.0)
        self.event_bus.stop()

    def run_pipeline_once(self):
        payloads = self.graph_runtime.run_ingestion_cycle(self.ingestion_agent.tickers, market=self.market)
        for payload in payloads:
            analysis = self.graph_runtime.analyze_filing(payload)
            if analysis:
                self.graph_runtime.index_analysis(analysis)
        return payloads


def parse_args():
    parser = argparse.ArgumentParser(description="Gravity Agentic Framework")
    parser.add_argument("--tickers", default="MSFT,AAPL", help="Comma-separated ticker symbols")
    parser.add_argument("--poll-interval", type=int, default=300, help="Ingestion poll interval in seconds")
    parser.add_argument("--market", default="US_SEC", choices=["US_SEC", "SEA_LOCAL"], help="Target market for ingestion")
    parser.add_argument("--run-once", action="store_true", help="Run one cycle and exit")
    return parser.parse_args()


def build_runtime(tickers, poll_interval_seconds=300, market="US_SEC"):
    return FrameworkRuntime(tickers=tickers, poll_interval_seconds=poll_interval_seconds, market=market)


def main():
    args = parse_args()
    tickers = [item.strip().upper() for item in args.tickers.split(",") if item.strip()]
    runtime = build_runtime(tickers=tickers, poll_interval_seconds=args.poll_interval, market=args.market)

    if args.run_once:
        payloads = runtime.run_pipeline_once()
        print("Processed filings:", len(payloads))
        return

    runtime.start()
    print("Framework runtime started. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping runtime...")
        runtime.stop()


if __name__ == "__main__":
    main()
