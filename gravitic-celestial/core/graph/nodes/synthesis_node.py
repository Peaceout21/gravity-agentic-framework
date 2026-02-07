"""LangGraph nodes for user question synthesis workflow."""


class SynthesisNodes(object):
    def __init__(self, rag_engine, synthesis_engine):
        self.rag_engine = rag_engine
        self.synthesis_engine = synthesis_engine

    @staticmethod
    def _merge(state, updates):
        merged = dict(state)
        merged.update(updates)
        return merged

    def parse_question(self, state):
        question = (state.get("question") or "").strip()
        return self._merge(
            state,
            {
                "question": question,
                "trace": state.get("trace", []) + ["parse_question"],
            },
        )

    def retrieve_semantic(self, state):
        semantic = self.rag_engine.semantic_search(state.get("question", ""), top_k=8)
        return self._merge(
            state,
            {
                "semantic_results": [serialize_result(item) for item in semantic],
                "trace": state.get("trace", []) + ["retrieve_semantic"],
            },
        )

    def retrieve_keyword(self, state):
        keyword = self.rag_engine.keyword_search(state.get("question", ""), top_k=8)
        return self._merge(
            state,
            {
                "keyword_results": [serialize_result(item) for item in keyword],
                "trace": state.get("trace", []) + ["retrieve_keyword"],
            },
        )

    def rrf_fuse(self, state):
        semantic = [deserialize_result(item) for item in state.get("semantic_results", [])]
        keyword = [deserialize_result(item) for item in state.get("keyword_results", [])]
        fused = self.rag_engine.reciprocal_rank_fusion(semantic, keyword, top_k=8)
        return self._merge(
            state,
            {
                "retrieval_results": [serialize_result(item) for item in fused],
                "trace": state.get("trace", []) + ["rrf_fuse"],
            },
        )

    def synthesize_answer(self, state):
        retrieval_results = state.get("retrieval_results", [])
        contexts = [item["text"] for item in retrieval_results]
        citations = [
            "%s:%s" % (item["metadata"].get("accession_number", ""), item["metadata"].get("kind", ""))
            for item in retrieval_results
        ]
        answer = self.synthesis_engine.synthesize(state.get("question", ""), contexts)
        return self._merge(
            state,
            {
                "answer": answer,
                "answer_citations": citations,
                "trace": state.get("trace", []) + ["synthesize_answer"],
            },
        )


def serialize_result(result):
    return {
        "chunk_id": result.chunk_id,
        "text": result.text,
        "metadata": result.metadata,
        "score": result.score,
    }


class _Result(object):
    def __init__(self, chunk_id, text, metadata, score):
        self.chunk_id = chunk_id
        self.text = text
        self.metadata = metadata
        self.score = score


def deserialize_result(result):
    return _Result(
        chunk_id=result.get("chunk_id"),
        text=result.get("text", ""),
        metadata=result.get("metadata", {}),
        score=float(result.get("score", 0.0)),
    )
