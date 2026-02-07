"""Knowledge agent that indexes analysis outputs and serves retrieval queries."""

from core.agents.base_agent import BaseAgent
from core.framework.messages import AnalysisPayload, TOPIC_ANALYSIS_COMPLETED


class KnowledgeAgent(BaseAgent):
    def __init__(self, event_bus, graph_runtime):
        self.graph_runtime = graph_runtime
        super(KnowledgeAgent, self).__init__(name="KnowledgeAgent", event_bus=event_bus)

    def _setup(self):
        self.bus.subscribe(TOPIC_ANALYSIS_COMPLETED, self.handle_message)

    def start(self):
        self.running = True

    def handle_message(self, message):
        payload = AnalysisPayload(**message.payload)
        self.graph_runtime.index_analysis(payload)

    def query(self, text, top_k=8):
        return self.graph_runtime.synthesis_nodes.rag_engine.query(text, top_k=top_k)
