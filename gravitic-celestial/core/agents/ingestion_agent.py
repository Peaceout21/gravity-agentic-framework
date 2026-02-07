"""Ingestion agent wrapper around the ingestion LangGraph."""

import time

from core.agents.base_agent import BaseAgent
from core.framework.messages import TOPIC_FILING_FOUND


class IngestionAgent(BaseAgent):
    def __init__(self, event_bus, graph_runtime, tickers, poll_interval_seconds=300):
        self.graph_runtime = graph_runtime
        self.tickers = tickers
        self.poll_interval_seconds = poll_interval_seconds
        super(IngestionAgent, self).__init__(name="IngestionAgent", event_bus=event_bus)

    def start(self):
        self.running = True
        while self.running:
            payloads = self.graph_runtime.run_ingestion_cycle(self.tickers)
            for payload in payloads:
                self.publish(TOPIC_FILING_FOUND, payload.dict())
            time.sleep(self.poll_interval_seconds)

    def handle_message(self, message):
        return None
