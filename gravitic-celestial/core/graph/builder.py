"""LangGraph builder and runtime service interface."""

import json
from typing import Any, Dict, List, Optional

from core.framework.messages import AnalysisPayload, FilingPayload, IndexReceipt, MarkdownAnswer
from core.graph.checkpoint import SQLiteCheckpointStore
from core.graph.nodes.analyst_node import AnalystNodes
from core.graph.nodes.ingestion_node import IngestionNodes
from core.graph.nodes.knowledge_node import KnowledgeNodes
from core.graph.nodes.synthesis_node import SynthesisNodes
from core.tools.edgar_client import FilingRecord

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

    def _safe_log_event(self, topic, source, payload=None):
        # type: (str, str, Optional[dict]) -> None
        if not hasattr(self.state_manager, "log_event"):
            return
        try:
            payload_text = json.dumps(payload or {}, ensure_ascii=True)
            self.state_manager.log_event(topic, source, payload_text)
        except Exception:
            # Logging should never break pipeline execution.
            pass

    @staticmethod
    def _model_dump(value):
        # type: (Any) -> Any
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if hasattr(value, "dict"):
            return value.dict()
        return value

    def _serialize_state(self, value):
        # type: (Any) -> Any
        if isinstance(value, dict):
            return {k: self._serialize_state(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._serialize_state(v) for v in value]
        dumped = self._model_dump(value)
        if dumped is not value:
            return self._serialize_state(dumped)
        return value

    @staticmethod
    def _to_filing_payload(value):
        # type: (Any) -> FilingPayload
        if isinstance(value, FilingPayload):
            return value
        if isinstance(value, dict):
            return FilingPayload(**value)
        raise ValueError("Invalid filing payload type: %s" % type(value).__name__)

    @staticmethod
    def _to_analysis_payload(value):
        # type: (Any) -> AnalysisPayload
        if isinstance(value, AnalysisPayload):
            return value
        if isinstance(value, dict):
            return AnalysisPayload(**value)
        raise ValueError("Invalid analysis payload type: %s" % type(value).__name__)

    @staticmethod
    def _to_index_receipt(value, accession_number):
        # type: (Any, str) -> IndexReceipt
        if isinstance(value, IndexReceipt):
            return value
        if isinstance(value, dict):
            return IndexReceipt(**value)
        chunk_count = getattr(value, "chunk_count", None)
        if chunk_count is not None:
            return IndexReceipt(accession_number=accession_number, chunk_count=int(chunk_count))
        raise ValueError("Invalid index receipt type: %s" % type(value).__name__)

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
        graph.add_node("derive_metric", self.synthesis_nodes.derive_metric)
        graph.add_node("synthesize_answer", self.synthesis_nodes.synthesize_answer)

        graph.set_entry_point("parse_question")
        graph.add_edge("parse_question", "retrieve_semantic")
        graph.add_edge("retrieve_semantic", "retrieve_keyword")
        graph.add_edge("retrieve_keyword", "rrf_fuse")
        graph.add_edge("rrf_fuse", "derive_metric")
        graph.add_edge("derive_metric", "synthesize_answer")
        graph.add_edge("synthesize_answer", END)
        return graph.compile()

    def run_ingestion_cycle(self, tickers, market="US_SEC", exchange=""):
        self.ingestion_nodes.tickers = tickers
        self.ingestion_nodes.market = (market or "US_SEC").upper()
        self.ingestion_nodes.exchange = exchange or ""
        initial_state = {"trace": [], "errors": []}
        final_state = self.ingestion_graph.invoke(initial_state)
        serialized = self._serialize_state(final_state)
        self.checkpoint_store.save_state("ingestion", "default", serialized)
        payloads = []
        for item in list(final_state.get("filing_payloads", [])):
            try:
                payloads.append(self._to_filing_payload(item))
            except Exception as exc:
                final_state.setdefault("errors", []).append("invalid_filing_payload:%s" % exc)
        self._safe_log_event(
            "INGESTION_CYCLE",
            "graph_runtime",
            {
                "tickers": tickers,
                "market": self.ingestion_nodes.market,
                "exchange": self.ingestion_nodes.exchange,
                "filings_found": len(payloads),
                "errors": list(final_state.get("errors", [])),
            },
        )
        return payloads

    def analyze_filing(self, payload):
        payload = self._to_filing_payload(payload)
        state = {"filing_payload": payload, "trace": [], "errors": []}
        try:
            final_state = self.analysis_graph.invoke(state)
            serialized = self._serialize_state(final_state)
            self.checkpoint_store.save_state("analysis", payload.accession_number, serialized)
        except Exception as exc:
            self.state_manager.mark_dead_letter(
                payload.accession_number,
                payload.ticker,
                payload.filing_url,
                reason="analysis_graph_exception",
                error=str(exc),
            )
            self._safe_log_event(
                "ANALYSIS_DEAD_LETTER",
                "graph_runtime",
                {
                    "ticker": payload.ticker,
                    "accession_number": payload.accession_number,
                    "errors": [str(exc)],
                },
            )
            return None

        if final_state.get("analysis"):
            self.state_manager.mark_analyzed(payload.accession_number, payload.ticker, payload.filing_url)
            self._safe_log_event(
                "ANALYSIS_SUCCESS",
                "graph_runtime",
                {"ticker": payload.ticker, "accession_number": payload.accession_number},
            )
            return self._to_analysis_payload(final_state.get("analysis"))

        dead_letter = final_state.get("dead_letter") or {}
        reason = dead_letter.get("reason") if isinstance(dead_letter, dict) else ""
        error_text = "; ".join([str(item) for item in final_state.get("errors", []) if item])
        self.state_manager.mark_dead_letter(
            payload.accession_number,
            payload.ticker,
            payload.filing_url,
            reason=(reason or "analysis_validation_failed"),
            error=error_text,
        )
        self._safe_log_event(
            "ANALYSIS_DEAD_LETTER",
            "graph_runtime",
            {
                "ticker": payload.ticker,
                "accession_number": payload.accession_number,
                "errors": final_state.get("errors", []),
            },
        )
        return None

    def index_analysis(self, payload):
        payload = self._to_analysis_payload(payload)
        state = {"analysis": payload, "trace": [], "errors": []}
        try:
            final_state = self.knowledge_graph.invoke(state)
            receipt = self._to_index_receipt(final_state.get("index_receipt"), payload.accession_number)
            serialized = self._serialize_state(final_state)
            self.checkpoint_store.save_state("knowledge", payload.accession_number, serialized)
            chunk_count = None
            if hasattr(receipt, "chunk_count"):
                chunk_count = receipt.chunk_count
            elif isinstance(receipt, dict):
                chunk_count = receipt.get("chunk_count")
            self._safe_log_event(
                "INDEX_SUCCESS",
                "graph_runtime",
                {"ticker": payload.ticker, "accession_number": payload.accession_number, "chunk_count": chunk_count},
            )
            return receipt
        except Exception as exc:
            self.state_manager.mark_analyzed_not_indexed(payload.accession_number, payload.ticker, "")
            self._safe_log_event(
                "INDEX_FAILURE",
                "graph_runtime",
                {"ticker": payload.ticker, "accession_number": payload.accession_number, "error": str(exc)},
            )
            raise

    def answer_question(self, question, ticker=None):
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a non-empty string")
        state = {
            "question": question.strip(),
            "ticker": ticker,
            "trace": [],
            "errors": [],
        }
        final_state = self.query_graph.invoke(state)
        serialized = self._serialize_state(final_state)
        self.checkpoint_store.save_state("query", question.strip(), serialized)
        self._safe_log_event(
            "QUERY_ANSWERED",
            "graph_runtime",
            {"ticker": ticker, "citations": len(final_state.get("answer_citations", []))},
        )
        return MarkdownAnswer(
            question=question.strip(),
            answer_markdown=final_state.get("answer", ""),
            citations=final_state.get("answer_citations", []),
            confidence=float(final_state.get("answer_confidence", 0.0) or 0.0),
            derivation_trace=list(final_state.get("derivation_trace", []) or []),
        )

    def replay_filing(self, accession_number, mode="auto"):
        # type: (str, str) -> Dict[str, Any]
        accession = (accession_number or "").strip()
        if not accession:
            raise ValueError("accession_number is required")
        normalized_mode = (mode or "auto").strip().lower()
        if normalized_mode not in ("auto", "analysis", "index"):
            raise ValueError("Unsupported replay mode: %s" % normalized_mode)

        filing = self.state_manager.get_filing(accession)
        if not filing:
            raise LookupError("Filing not found: %s" % accession)
        if hasattr(self.state_manager, "mark_replay_attempt"):
            self.state_manager.mark_replay_attempt(accession)

        selected_mode = normalized_mode
        if selected_mode == "auto":
            selected_mode = "index" if filing.get("status") == "ANALYZED_NOT_INDEXED" else "analysis"

        indexed = False
        analyzed = False
        analysis = None
        if selected_mode == "index":
            checkpoint_state = self.checkpoint_store.load_state("analysis", accession) or {}
            if checkpoint_state.get("analysis"):
                analysis = self._to_analysis_payload(checkpoint_state.get("analysis"))
            else:
                selected_mode = "analysis"

        if selected_mode == "analysis":
            metadata = {
                "filing_type": filing.get("filing_type", ""),
                "item_code": filing.get("item_code", ""),
                "filing_date": filing.get("filing_date", ""),
                "document_type": filing.get("document_type", ""),
                "currency": filing.get("currency", ""),
            }
            record = FilingRecord(
                ticker=filing.get("ticker", ""),
                accession_number=filing.get("accession_number", accession),
                filing_url=filing.get("filing_url", ""),
                filing_type=metadata.get("filing_type") or "8-K",
                market=filing.get("market", "US_SEC"),
                exchange=filing.get("exchange", ""),
                issuer_id=filing.get("issuer_id", ""),
                source=filing.get("source", ""),
                source_event_id=filing.get("source_event_id", accession),
                document_type=filing.get("document_type", ""),
                currency=filing.get("currency", ""),
                metadata=metadata,
            )
            provider = self.ingestion_nodes.edgar_client
            if hasattr(provider, "get_document_text"):
                raw_text = provider.get_document_text(record)
            else:
                raw_text = provider.get_filing_text(record)
            if not raw_text:
                raise RuntimeError("Replay failed: unable to fetch filing text")
            replay_payload = FilingPayload(
                market=filing.get("market", "US_SEC"),
                exchange=filing.get("exchange", ""),
                issuer_id=filing.get("issuer_id", ""),
                source=filing.get("source", ""),
                source_event_id=filing.get("source_event_id", accession),
                ticker=filing.get("ticker", ""),
                accession_number=filing.get("accession_number", accession),
                filing_url=filing.get("filing_url", ""),
                raw_text=raw_text,
                metadata=metadata,
            )
            analysis = self.analyze_filing(replay_payload)
            analyzed = analysis is not None
        if analysis is None:
            return {
                "status": "dead_letter",
                "accession_number": accession,
                "mode": selected_mode,
                "analyzed": analyzed,
                "indexed": indexed,
            }
        self.index_analysis(analysis)
        indexed = True
        if selected_mode == "index":
            analyzed = True
        self._safe_log_event(
            "FILING_REPLAYED",
            "graph_runtime",
            {"accession_number": accession, "mode": selected_mode, "analyzed": analyzed, "indexed": indexed},
        )
        return {
            "status": "ok",
            "accession_number": accession,
            "mode": selected_mode,
            "analyzed": analyzed,
            "indexed": indexed,
        }
