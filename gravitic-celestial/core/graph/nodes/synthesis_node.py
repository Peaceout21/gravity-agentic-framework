"""LangGraph nodes for user question synthesis workflow."""

import re

from core.tools.extraction_engine import safe_json_extract


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

    def derive_metric(self, state):
        question = state.get("question", "")
        retrieval_results = state.get("retrieval_results", [])
        contexts = [item["text"] for item in retrieval_results][:4]
        if not question or not contexts:
            return self._merge(
                state,
                {
                    "derived_answer": "",
                    "derivation_trace": [],
                    "answer_confidence": 0.0,
                    "trace": state.get("trace", []) + ["derive_metric_skipped"],
                },
            )

        prompt = (
            "Given the question and evidence snippets, derive the requested metric only if supported by evidence. "
            "Return JSON with keys derived_answer (string), confidence (0 to 1), derivation_trace (array of short steps). "
            "If unsupported, set derived_answer to empty string and confidence to 0.\n\n"
            "Question:\n%s\n\nEvidence:\n%s"
            % (question, "\n\n".join(contexts))
        )
        generator = getattr(self.synthesis_engine, "adapter", None)
        generate_json = getattr(generator, "generate_json", None)
        parsed = {}
        if callable(generate_json):
            parsed = generate_json(prompt) or {}
        if not isinstance(parsed, dict) or not parsed:
            # Fallback: attempt text response parsed as JSON.
            generate_text = getattr(generator, "generate_text", None)
            if callable(generate_text):
                parsed = safe_json_extract(generate_text(prompt) or "")
        if not isinstance(parsed, dict):
            parsed = {}

        derived_answer = str(parsed.get("derived_answer", "") or "").strip()
        if derived_answer and _looks_like_non_answer(derived_answer):
            derived_answer = ""
        confidence = _clamp_confidence(parsed.get("confidence", 0.0))
        raw_trace = parsed.get("derivation_trace", [])
        if not isinstance(raw_trace, list):
            raw_trace = []
        derivation_trace = [str(item).strip() for item in raw_trace if str(item).strip()][:5]
        if not derived_answer:
            confidence = 0.0
            derivation_trace = []

        return self._merge(
            state,
            {
                "derived_answer": derived_answer,
                "derivation_trace": derivation_trace,
                "answer_confidence": confidence,
                "trace": state.get("trace", []) + ["derive_metric"],
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
        derived_answer = (state.get("derived_answer") or "").strip()
        derivation_trace = state.get("derivation_trace", []) or []
        confidence = float(state.get("answer_confidence", 0.0) or 0.0)

        if derived_answer:
            answer = "%s\n\n### Derived Metric\n%s" % (answer, derived_answer)
            if derivation_trace:
                answer = "%s\n\n### Derivation Trace\n- %s" % (answer, "\n- ".join(derivation_trace))

        if confidence <= 0.0:
            confidence = _heuristic_confidence(contexts, citations)
        return self._merge(
            state,
            {
                "answer": answer,
                "answer_citations": citations,
                "derivation_trace": derivation_trace,
                "answer_confidence": _clamp_confidence(confidence),
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


def _heuristic_confidence(contexts, citations):
    # type: (list, list) -> float
    if not contexts:
        return 0.0
    if citations and len(citations) >= 2:
        return 0.8
    if citations:
        return 0.65
    return 0.35


def _clamp_confidence(value):
    # type: (object) -> float
    try:
        score = float(value)
    except Exception:
        return 0.0
    if score < 0:
        return 0.0
    if score > 1:
        return 1.0
    return round(score, 4)


def _looks_like_non_answer(text):
    # type: (str) -> bool
    normalized = text.lower().strip()
    if not normalized:
        return True
    patterns = [
        r"insufficient context",
        r"not enough information",
        r"cannot determine",
        r"no information",
        r"unknown",
    ]
    return any(re.search(pattern, normalized) for pattern in patterns)
