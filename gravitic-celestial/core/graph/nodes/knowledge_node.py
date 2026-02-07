"""LangGraph nodes for knowledge indexing workflow."""

from core.framework.messages import IndexReceipt


class KnowledgeNodes(object):
    def __init__(self, rag_engine):
        self.rag_engine = rag_engine

    @staticmethod
    def _merge(state, updates):
        merged = dict(state)
        merged.update(updates)
        return merged

    def chunk_kpi_and_summary(self, state):
        analysis = state.get("analysis")
        if analysis is None:
            return self._merge(state, {"chunks": [], "trace": state.get("trace", []) + ["chunk_empty"]})

        chunks = []
        for idx, kpi in enumerate(analysis.kpis):
            text = "KPI %s: %s = %s" % (idx + 1, kpi.get("metric", ""), kpi.get("value", ""))
            chunks.append(
                {
                    "id": "%s-kpi-%s" % (analysis.accession_number, idx),
                    "text": text,
                    "metadata": {
                        "ticker": analysis.ticker,
                        "accession_number": analysis.accession_number,
                        "kind": "kpi",
                    },
                }
            )

        highlights = analysis.summary.get("highlights", []) if isinstance(analysis.summary, dict) else []
        if highlights:
            narrative = "Summary: %s" % " ".join(highlights)
            chunks.append(
                {
                    "id": "%s-summary" % analysis.accession_number,
                    "text": narrative,
                    "metadata": {
                        "ticker": analysis.ticker,
                        "accession_number": analysis.accession_number,
                        "kind": "summary",
                    },
                }
            )
        return self._merge(state, {"chunks": chunks, "trace": state.get("trace", []) + ["chunk_kpi_and_summary"]})

    def index_chroma(self, state):
        chunks = state.get("chunks", [])
        if chunks:
            self.rag_engine.add_documents(chunks)
        return self._merge(state, {"trace": state.get("trace", []) + ["index_chroma"]})

    def update_bm25(self, state):
        self.rag_engine._load_bm25_index()
        return self._merge(state, {"trace": state.get("trace", []) + ["update_bm25"]})

    def persist_receipt(self, state):
        analysis = state.get("analysis")
        chunks = state.get("chunks", [])
        receipt = IndexReceipt(accession_number=analysis.accession_number, chunk_count=len(chunks))
        return self._merge(state, {"index_receipt": receipt, "trace": state.get("trace", []) + ["persist_receipt"]})
