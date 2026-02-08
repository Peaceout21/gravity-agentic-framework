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


class InferFilingTypeTests(unittest.TestCase):
    """Test the _infer_filing_type heuristic directly."""

    def test_canonical_path_segments(self):
        from core.framework.state_manager import _infer_filing_type

        self.assertEqual(_infer_filing_type("https://sec.gov/Archives/edgar/data/123/10-Q/doc.htm"), "10-Q")
        self.assertEqual(_infer_filing_type("https://sec.gov/Archives/edgar/data/123/8-K/doc.htm"), "8-K")
        self.assertEqual(_infer_filing_type("https://sec.gov/Archives/edgar/data/123/10-K/doc.htm"), "10-K")
        self.assertEqual(_infer_filing_type("https://sec.gov/Archives/edgar/data/123/20-F/doc.htm"), "20-F")

    def test_compact_tokens_def14a(self):
        from core.framework.state_manager import _infer_filing_type

        self.assertEqual(_infer_filing_type("https://sec.gov/Archives/edgar/data/123/000/def14a.htm"), "DEF 14A")

    def test_compact_tokens_sc13d(self):
        from core.framework.state_manager import _infer_filing_type

        self.assertEqual(_infer_filing_type("https://sec.gov/Archives/edgar/data/123/000/sc13d.htm"), "SC 13D")

    def test_compact_tokens_in_filename(self):
        from core.framework.state_manager import _infer_filing_type

        self.assertEqual(
            _infer_filing_type("https://sec.gov/Archives/edgar/data/123/000/msft-20240630_10q.htm"),
            "10-Q",
        )
        self.assertEqual(
            _infer_filing_type("https://sec.gov/Archives/edgar/data/123/000/aapl-20f.htm"),
            "20-F",
        )

    def test_unknown_url_returns_none(self):
        from core.framework.state_manager import _infer_filing_type

        self.assertIsNone(_infer_filing_type("https://sec.gov/cgi-bin/browse-edgar?action=getcompany"))
        self.assertIsNone(_infer_filing_type(""))
        self.assertIsNone(_infer_filing_type(None))


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

    def test_backfill_canonical_urls(self):
        import os
        import tempfile
        from core.framework.state_manager import StateManager

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            sm = StateManager(db_path=path)
            sm.upsert_filing("ACC001", "MSFT", "https://sec.gov/Archives/edgar/data/123/10-Q/doc.htm", "ANALYZED")
            sm.upsert_filing("ACC002", "AAPL", "https://sec.gov/Archives/edgar/data/456/8-K/doc.htm", "ANALYZED")
            sm.upsert_filing("ACC003", "GOOG", "https://sec.gov/Archives/edgar/data/789/unknown/doc.htm", "ANALYZED")
            # Already has filing_type — should not be overwritten
            sm.upsert_filing("ACC004", "TSLA", "https://sec.gov/Archives/edgar/data/000/10-K/doc.htm", "ANALYZED",
                             filing_type="10-K")

            result = sm.backfill_filing_metadata()
            self.assertEqual(result["updated_count"], 2)
            self.assertEqual(result["skipped_count"], 1)  # ACC003
            self.assertEqual(result["total_scanned"], 3)  # ACC004 excluded (already has type)
            self.assertIn("ACC001", result["samples"])

            filings = sm.list_recent_filings(limit=10)
            by_acc = {f["accession_number"]: f for f in filings}
            self.assertEqual(by_acc["ACC001"]["filing_type"], "10-Q")
            self.assertEqual(by_acc["ACC002"]["filing_type"], "8-K")
            self.assertEqual(by_acc["ACC003"]["filing_type"], "")
            self.assertEqual(by_acc["ACC004"]["filing_type"], "10-K")
        finally:
            os.unlink(path)

    def test_backfill_compact_tokens(self):
        """Compact EDGAR tokens like def14a and sc13d should be recognised."""
        import os
        import tempfile
        from core.framework.state_manager import StateManager

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            sm = StateManager(db_path=path)
            sm.upsert_filing("ACC010", "MSFT", "https://sec.gov/Archives/edgar/data/123/000/def14a.htm", "ANALYZED")
            sm.upsert_filing("ACC011", "AAPL", "https://sec.gov/Archives/edgar/data/456/000/sc13d.htm", "ANALYZED")
            sm.upsert_filing("ACC012", "GOOG", "https://sec.gov/Archives/edgar/data/789/000/goog-20240630_10q.htm", "ANALYZED")

            result = sm.backfill_filing_metadata()
            self.assertEqual(result["updated_count"], 3)
            self.assertEqual(result["skipped_count"], 0)

            filings = sm.list_recent_filings(limit=10)
            by_acc = {f["accession_number"]: f for f in filings}
            self.assertEqual(by_acc["ACC010"]["filing_type"], "DEF 14A")
            self.assertEqual(by_acc["ACC011"]["filing_type"], "SC 13D")
            self.assertEqual(by_acc["ACC012"]["filing_type"], "10-Q")
        finally:
            os.unlink(path)

    def test_backfill_idempotent(self):
        """Running backfill twice should not change results."""
        import os
        import tempfile
        from core.framework.state_manager import StateManager

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            sm = StateManager(db_path=path)
            sm.upsert_filing("ACC020", "MSFT", "https://sec.gov/Archives/edgar/data/123/10-Q/doc.htm", "ANALYZED")

            r1 = sm.backfill_filing_metadata()
            self.assertEqual(r1["updated_count"], 1)

            r2 = sm.backfill_filing_metadata()
            self.assertEqual(r2["total_scanned"], 0)  # no rows left with empty type
            self.assertEqual(r2["updated_count"], 0)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
