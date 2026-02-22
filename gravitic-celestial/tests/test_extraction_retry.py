import unittest

from core.graph.nodes.analyst_node import normalize_analysis_dict
from core.tools.extraction_engine import ExtractionEngine


class FlakyAdapter(object):
    def __init__(self):
        self.calls = 0

    def generate_json(self, prompt):
        self.calls += 1
        if self.calls == 1:
            return {"kpis": [{"metric": "EPS", "value": "$1.00"}], "summary": {}, "guidance": []}
        return {"kpis": [{"metric": "Revenue", "value": "$50B"}], "summary": {}, "guidance": []}


class ExtractionRetryTests(unittest.TestCase):
    def test_reflection_retry_recovers_missing_revenue(self):
        adapter = FlakyAdapter()
        engine = ExtractionEngine(adapter=adapter)
        result = engine.extract_with_reflection("example")
        self.assertTrue(engine.is_valid(result))
        self.assertEqual(adapter.calls, 2)

    def test_revenue_alias_is_accepted_and_normalized(self):
        class AliasAdapter(object):
            def generate_json(self, prompt):
                _ = prompt
                return {"kpis": [{"metric": "Net Sales", "value": "$10B"}], "summary": {}, "guidance": []}

        engine = ExtractionEngine(adapter=AliasAdapter())
        result = engine.extract("example")
        self.assertEqual(result["kpis"][0]["metric"], "Revenue")
        self.assertTrue(engine.is_valid(result))

    def test_analysis_normalization_coerces_numeric_values_to_strings(self):
        normalized = normalize_analysis_dict(
            {
                "kpis": [{"metric": "Revenue", "value": 12345}, {"metric": "EPS", "value": 2.84}],
                "summary": {"highlights": ["Strong quarter"], "margin": 44.2},
                "guidance": [{"fy_revenue": 100000}],
            }
        )
        self.assertEqual(normalized["kpis"][0]["value"], "12345")
        self.assertEqual(normalized["kpis"][1]["value"], "2.84")
        self.assertEqual(normalized["summary"]["margin"][0], "44.2")
        self.assertEqual(normalized["guidance"][0]["fy_revenue"], "100000")


if __name__ == "__main__":
    unittest.main()
