import unittest

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


if __name__ == "__main__":
    unittest.main()
