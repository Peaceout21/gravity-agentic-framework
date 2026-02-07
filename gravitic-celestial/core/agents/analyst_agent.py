"""Analyst agent that subscribes to filing events and emits analysis."""

from core.agents.base_agent import BaseAgent
from core.framework.messages import AnalysisPayload, FilingPayload, TOPIC_ANALYSIS_COMPLETED, TOPIC_FILING_FOUND


class AnalystAgent(BaseAgent):
    def __init__(self, event_bus, graph_runtime):
        self.graph_runtime = graph_runtime
        super(AnalystAgent, self).__init__(name="AnalystAgent", event_bus=event_bus)

    def _setup(self):
        self.bus.subscribe(TOPIC_FILING_FOUND, self.handle_message)

    def start(self):
        self.running = True

    def handle_message(self, message):
        payload = FilingPayload(**message.payload)
        analysis = self.graph_runtime.analyze_filing(payload)
        if analysis:
            self.publish(TOPIC_ANALYSIS_COMPLETED, analysis.dict())
