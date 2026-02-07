"""Synthesis agent for user-facing question answering."""

from core.agents.base_agent import BaseAgent


class SynthesisAgent(BaseAgent):
    def __init__(self, event_bus, graph_runtime):
        self.graph_runtime = graph_runtime
        super(SynthesisAgent, self).__init__(name="SynthesisAgent", event_bus=event_bus)

    def start(self):
        self.running = True

    def handle_message(self, message):
        return None

    def answer(self, question, ticker=None):
        return self.graph_runtime.answer_question(question=question, ticker=ticker)
