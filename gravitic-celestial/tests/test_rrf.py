import unittest

from core.tools.hybrid_rag import HybridRAGEngine, SearchResult


class RRFTests(unittest.TestCase):
    def test_rrf_orders_by_combined_rank(self):
        semantic = [
            SearchResult(chunk_id="a", text="A", metadata={}, score=0.9),
            SearchResult(chunk_id="b", text="B", metadata={}, score=0.8),
        ]
        keyword = [
            SearchResult(chunk_id="b", text="B", metadata={}, score=11.0),
            SearchResult(chunk_id="a", text="A", metadata={}, score=10.0),
        ]
        fused = HybridRAGEngine.reciprocal_rank_fusion(semantic, keyword, top_k=2)
        self.assertEqual(len(fused), 2)
        self.assertEqual(fused[0].chunk_id, "a")


if __name__ == "__main__":
    unittest.main()
