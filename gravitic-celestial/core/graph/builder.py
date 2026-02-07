"""LangGraph builder and runtime service interface."""

from typing import List, Optional

from core.framework.messages import MarkdownAnswer
from core.graph.checkpoint import SQLiteCheckpointStore
from core.graph.nodes.analyst_node import AnalystNodes
from core.graph.nodes.ingestion_node import IngestionNodes
from core.graph.nodes.knowledge_node import KnowledgeNodes
from core.graph.nodes.synthesis_node import SynthesisNodes

try:
    from langgraph.graph import END, StateGraph
except Exception as exc:  # pragma: no cover
    END = "__end__"
    StateGraph = None
    _LANGGRAPH_IMPORT_ERROR = exc
else:
    _LANGGRAPH_IMPORT_ERROR = None


class GraphRuntime(object):
    def __init__(
        self,
        state_manager,
        edgar_client,
        extraction_engine,
        rag_engine,
        synthesis_engine,
        tickers,
        checkpoint_store=None,
    ):
        if StateGraph is None:
            raise RuntimeError("langgraph is required to run GraphRuntime: %s" % _LANGGRAPH_IMPORT_ERROR)

        self.state_manager = state_manager
        self.checkpoint_store = checkpoint_store or SQLiteCheckpointStore()

        self.ingestion_nodes = IngestionNodes(edgar_client=edgar_client, state_manager=state_manager, tickers=tickers)
        self.analyst_nodes = AnalystNodes(extraction_engine=extraction_engine)
        self.knowledge_nodes = KnowledgeNodes(rag_engine=rag_engine)
        self.synthesis_nodes = SynthesisNodes(rag_engine=rag_engine, synthesis_engine=synthesis_engine)

        self.ingestion_graph = self._build_ingestion_graph()
        self.analysis_graph = self._build_analysis_graph()
        self.knowledge_graph = self._build_knowledge_graph()
        self.query_graph = self._build_query_graph()

    def _build_ingestion_graph(self):
        graph = StateGraph(dict)
        graph.add_node("poll_edgar", self.ingestion_nodes.poll_edgar)
        graph.add_node("dedupe_check", self.ingestion_nodes.dedupe_check)
        graph.add_node("fetch_full_text", self.ingestion_nodes.fetch_full_text)
        graph.add_node("fetch_exhibits", self.ingestion_nodes.fetch_exhibits)
        graph.add_node("merge_text", self.ingestion_nodes.merge_text)
        graph.add_node("emit_payload", self.ingestion_nodes.emit_filing_payload)

        graph.set_entry_point("poll_edgar")
        graph.add_edge("poll_edgar", "dedupe_check")
        graph.add_edge("dedupe_check", "fetch_full_text")

        graph.add_conditional_edges(
            "fetch_full_text",
            self.ingestion_nodes.route_exhibit_logic,
            {
                "fetch_exhibits": "fetch_exhibits",
                "emit_payload": "emit_payload",
                "no_payload": END,
            },
        )
        graph.add_edge("fetch_exhibits", "merge_text")
        graph.add_edge("merge_text", "emit_payload")

        graph.add_conditional_edges(
            "emit_payload",
            self.ingestion_nodes.route_continue_or_end,
            {"continue": "fetch_full_text", "end": END},
        )
        return graph.compile()

    def _build_analysis_graph(self):
        graph = StateGraph(dict)
        graph.add_node("build_prompt", self.analyst_nodes.build_prompt)
        graph.add_node("call_gemini_extract", self.analyst_nodes.call_gemini_extract)
        graph.add_node("validate_json", self.analyst_nodes.validate_json)
        graph.add_node("reflection_retry_once", self.analyst_nodes.reflection_retry_once)
        graph.add_node("dead_letter", self.analyst_nodes.dead_letter)
        graph.add_node("emit_analysis_payload", self.analyst_nodes.emit_analysis_payload)

        graph.set_entry_point("build_prompt")
        graph.add_edge("build_prompt", "call_gemini_extract")
        graph.add_edge("call_gemini_extract", "validate_json")
        graph.add_conditional_edges(
            "validate_json",
            self.analyst_nodes.route_after_validation,
            {
                "reflect": "reflection_retry_once",
                "dead_letter": "dead_letter",
                "emit": "emit_analysis_payload",
            },
        )
        graph.add_edge("reflection_retry_once", "validate_json")
        graph.add_edge("dead_letter", END)
        graph.add_edge("emit_analysis_payload", END)
        return graph.compile()

    def _build_knowledge_graph(self):
        graph = StateGraph(dict)
        graph.add_node("chunk_kpi_and_summary", self.knowledge_nodes.chunk_kpi_and_summary)
        graph.add_node("index_chroma", self.knowledge_nodes.index_chroma)
        graph.add_node("update_bm25", self.knowledge_nodes.update_bm25)
        graph.add_node("persist_receipt", self.knowledge_nodes.persist_receipt)

        graph.set_entry_point("chunk_kpi_and_summary")
        graph.add_edge("chunk_kpi_and_summary", "index_chroma")
        graph.add_edge("index_chroma", "update_bm25")
        graph.add_edge("update_bm25", "persist_receipt")
        graph.add_edge("persist_receipt", END)
        return graph.compile()

    def _build_query_graph(self):
        graph = StateGraph(dict)
        graph.add_node("parse_question", self.synthesis_nodes.parse_question)
        graph.add_node("retrieve_semantic", self.synthesis_nodes.retrieve_semantic)
        graph.add_node("retrieve_keyword", self.synthesis_nodes.retrieve_keyword)
        graph.add_node("rrf_fuse", self.synthesis_nodes.rrf_fuse)
        graph.add_node("synthesize_answer", self.synthesis_nodes.synthesize_answer)

        graph.set_entry_point("parse_question")
        graph.add_edge("parse_question", "retrieve_semantic")
        graph.add_edge("retrieve_semantic", "retrieve_keyword")
        graph.add_edge("retrieve_keyword", "rrf_fuse")
        graph.add_edge("rrf_fuse", "synthesize_answer")
        graph.add_edge("synthesize_answer", END)
        return graph.compile()

    def run_ingestion_cycle(self, tickers):
        self.ingestion_nodes.tickers = tickers
        initial_state = {"trace": [], "errors": []}
        final_state = self.ingestion_graph.invoke(initial_state)
        self.checkpoint_store.save_state("ingestion", "default", final_state)
        return list(final_state.get("filing_payloads", []))

    def analyze_filing(self, payload):
        state = {"filing_payload": payload, "trace": [], "errors": []}
        final_state = self.analysis_graph.invoke(state)
        self.checkpoint_store.save_state("analysis", payload.accession_number, final_state)
        if final_state.get("analysis"):
            self.state_manager.mark_analyzed(payload.accession_number, payload.ticker, payload.filing_url)
        else:
            self.state_manager.mark_dead_letter(payload.accession_number, payload.ticker, payload.filing_url)
        return final_state.get("analysis")

    def index_analysis(self, payload):
        state = {"analysis": payload, "trace": [], "errors": []}
        try:
            final_state = self.knowledge_graph.invoke(state)
            receipt = final_state.get("index_receipt")
            self.checkpoint_store.save_state("knowledge", payload.accession_number, final_state)
            return receipt
        except Exception:
            self.state_manager.mark_analyzed_not_indexed(payload.accession_number, payload.ticker, "")
            raise

    def answer_question(self, question, ticker=None):
        state = {
            "question": question,
            "ticker": ticker,
            "trace": [],
            "errors": [],
        }
        final_state = self.query_graph.invoke(state)
        self.checkpoint_store.save_state("query", question, final_state)
        return MarkdownAnswer(
            question=question,
            answer_markdown=final_state.get("answer", ""),
            citations=final_state.get("answer_citations", []),
        )
