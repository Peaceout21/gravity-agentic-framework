import unittest

from services.ask_templates import (
    _format_rule_hint,
    build_coverage_brief,
    compute_relevance,
    render_question,
)


class AskTemplatesServiceTests(unittest.TestCase):
    def test_render_question_with_defaults(self):
        template = {"question_template": "What changed for {ticker} in {period}?"}
        rendered = render_question(template, ticker="msft", params={})
        self.assertEqual(rendered, "What changed for MSFT in latest quarter?")

    def test_render_question_custom_period(self):
        template = {"question_template": "What changed for {ticker} in {period}?"}
        rendered = render_question(template, ticker="aapl", params={"period": "last two quarters"})
        self.assertEqual(rendered, "What changed for AAPL in last two quarters?")

    def test_compute_relevance_high(self):
        rules = [{"filing_type": "10-Q", "item_code": "", "weight": 1.0}]
        filings = [{"filing_type": "10-Q", "item_code": ""}]
        label, score = compute_relevance(rules, filings)
        self.assertEqual(label, "High relevance")
        self.assertEqual(score, 1.0)

    def test_compute_relevance_low_empty_filing_type(self):
        """Filings without filing_type should not match any rule."""
        rules = [{"filing_type": "10-Q", "item_code": "", "weight": 1.0}]
        filings = [{"filing_type": "", "item_code": ""}]
        label, score = compute_relevance(rules, filings)
        self.assertEqual(label, "Low relevance")
        self.assertEqual(score, 0.0)

    def test_build_coverage_brief_low_relevance_with_rules(self):
        filings = [
            {"filing_type": "8-K", "item_code": "2.02", "filing_date": "2026-01-31", "updated_at": "2026-01-31T00:00:00"}
        ]
        rules = [
            {"filing_type": "10-Q", "item_code": "", "weight": 1.0},
            {"filing_type": "10-K", "item_code": "", "weight": 0.9},
        ]
        brief = build_coverage_brief(filings, "Low relevance", template_rules=rules)
        self.assertIn("Best with:", brief)
        self.assertIn("10-Q", brief)
        self.assertIn("10-K", brief)
        self.assertIn("8-K Item 2.02", brief)

    def test_build_coverage_brief_low_relevance_no_rules(self):
        filings = [
            {"filing_type": "8-K", "item_code": "2.02", "filing_date": "2026-01-31", "updated_at": "2026-01-31T00:00:00"}
        ]
        brief = build_coverage_brief(filings, "Low relevance")
        self.assertIn("8-K", brief)

    def test_build_coverage_brief_no_filings_with_rules(self):
        rules = [
            {"filing_type": "10-Q", "item_code": "", "weight": 1.0},
        ]
        brief = build_coverage_brief([], "Low relevance", template_rules=rules)
        self.assertIn("Best with: 10-Q", brief)
        self.assertIn("Run ingestion", brief)

    def test_build_coverage_brief_high_relevance(self):
        filings = [
            {"filing_type": "10-Q", "item_code": "", "filing_date": "2026-01-15", "updated_at": "2026-01-15T00:00:00"}
        ]
        brief = build_coverage_brief(filings, "High relevance")
        self.assertIn("Based on analyzed filings:", brief)
        self.assertNotIn("Best with:", brief)

    def test_format_rule_hint(self):
        rules = [
            {"filing_type": "10-Q", "item_code": "", "weight": 1.0},
            {"filing_type": "8-K", "item_code": "2.02", "weight": 0.7},
        ]
        hint = _format_rule_hint(rules)
        self.assertEqual(hint, "Best with: 10-Q, 8-K Item 2.02.")

    def test_format_rule_hint_empty(self):
        self.assertEqual(_format_rule_hint(None), "")
        self.assertEqual(_format_rule_hint([]), "")


class StateManagerMetadataTests(unittest.TestCase):
    def test_count_filings_for_ticker(self):
        import os
        import tempfile
        from core.framework.state_manager import StateManager

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            sm = StateManager(db_path=path)
            self.assertEqual(sm.count_filings_for_ticker("MSFT"), 0)
            sm.mark_ingested("0001-01-01", "MSFT", "https://sec.gov/10-Q/doc.htm")
            self.assertEqual(sm.count_filings_for_ticker("MSFT"), 1)
            self.assertEqual(sm.count_filings_for_ticker("AAPL"), 0)
        finally:
            os.unlink(path)

    def test_backfill_filing_metadata(self):
        import os
        import tempfile
        from core.framework.state_manager import StateManager

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            sm = StateManager(db_path=path)
            # Insert filing with no filing_type
            sm.upsert_filing("ACC001", "MSFT", "https://sec.gov/Archives/edgar/data/123/10-Q/doc.htm", "ANALYZED")
            sm.upsert_filing("ACC002", "AAPL", "https://sec.gov/Archives/edgar/data/456/8-K/doc.htm", "ANALYZED")
            sm.upsert_filing("ACC003", "GOOG", "https://sec.gov/Archives/edgar/data/789/unknown/doc.htm", "ANALYZED")
            # Already has filing_type — should not be overwritten
            sm.upsert_filing("ACC004", "TSLA", "https://sec.gov/Archives/edgar/data/000/10-K/doc.htm", "ANALYZED",
                             filing_type="10-K")

            updated = sm.backfill_filing_metadata()
            self.assertEqual(updated, 2)  # ACC001 and ACC002 updated, ACC003 unmatched, ACC004 skipped

            filings = sm.list_recent_filings(limit=10)
            by_acc = {f["accession_number"]: f for f in filings}
            self.assertEqual(by_acc["ACC001"]["filing_type"], "10-Q")
            self.assertEqual(by_acc["ACC002"]["filing_type"], "8-K")
            self.assertEqual(by_acc["ACC003"]["filing_type"], "")
            self.assertEqual(by_acc["ACC004"]["filing_type"], "10-K")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
