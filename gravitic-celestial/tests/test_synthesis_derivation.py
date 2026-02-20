import unittest

from core.graph.nodes.synthesis_node import SynthesisNodes


class _Result(object):
    def __init__(self, chunk_id, text, metadata, score):
        self.chunk_id = chunk_id
        self.text = text
        self.metadata = metadata
        self.score = score


class _DummyRag(object):
    def semantic_search(self, question, top_k=8):
        _ = (question, top_k)
        return [
            _Result(
                "c1",
                "Revenue increased to 120 from 100 in the previous quarter.",
                {"accession_number": "ACC-1", "kind": "summary"},
                0.9,
            )
        ]

    def keyword_search(self, question, top_k=8):
        _ = (question, top_k)
        return [
            _Result(
                "c1",
                "Revenue increased to 120 from 100 in the previous quarter.",
                {"accession_number": "ACC-1", "kind": "summary"},
                1.0,
            )
        ]

    @staticmethod
    def reciprocal_rank_fusion(semantic, keyword, top_k=8):
        _ = (keyword, top_k)
        return semantic


class _DummyAdapter(object):
    def generate_json(self, prompt):
        _ = prompt
        return {
            "derived_answer": "Revenue growth is 20.0% quarter-over-quarter.",
            "confidence": 0.84,
            "derivation_trace": [
                "Identified current quarter revenue 120",
                "Identified previous quarter revenue 100",
                "Computed (120-100)/100",
            ],
        }


class _DummySynthesis(object):
    def __init__(self):
        self.adapter = _DummyAdapter()

    def synthesize(self, question, contexts):
        _ = (question, contexts)
        return "Base grounded answer."


class SynthesisDerivationTests(unittest.TestCase):
    def test_derivation_appended_and_confidence_propagated(self):
        nodes = SynthesisNodes(rag_engine=_DummyRag(), synthesis_engine=_DummySynthesis())
        state = {"question": "What is revenue growth?", "trace": [], "errors": []}
        state = nodes.parse_question(state)
        state = nodes.retrieve_semantic(state)
        state = nodes.retrieve_keyword(state)
        state = nodes.rrf_fuse(state)
        state = nodes.derive_metric(state)
        state = nodes.synthesize_answer(state)

        self.assertIn("Derived Metric", state.get("answer", ""))
        self.assertGreaterEqual(float(state.get("answer_confidence", 0.0)), 0.8)
        self.assertEqual(len(state.get("derivation_trace", [])), 3)


if __name__ == "__main__":
    unittest.main()
