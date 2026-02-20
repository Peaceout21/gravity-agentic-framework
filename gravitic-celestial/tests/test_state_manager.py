import os
import tempfile
import unittest

from core.framework.state_manager import StateManager


class StateManagerTests(unittest.TestCase):
    def test_dedupe_and_status_update(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "state.db")
            manager = StateManager(db_path=db_path)
            self.assertFalse(manager.has_accession("A1"))
            manager.mark_ingested("A1", "MSFT", "http://x")
            self.assertTrue(manager.has_accession("A1"))
            manager.mark_analyzed("A1", "MSFT", "http://x")
            filings = manager.list_recent_filings(limit=1)
            self.assertEqual(filings[0]["status"], "ANALYZED")

    def test_dead_letter_reason_and_replay_tracking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "state.db")
            manager = StateManager(db_path=db_path)
            manager.mark_ingested("A2", "AAPL", "http://f")
            manager.mark_dead_letter("A2", "AAPL", "http://f", reason="validation_failed", error="missing_kpi")
            filing = manager.get_filing("A2")
            self.assertEqual(filing["status"], "DEAD_LETTER")
            self.assertEqual(filing["dead_letter_reason"], "validation_failed")
            self.assertEqual(filing["last_error"], "missing_kpi")
            self.assertEqual(filing["replay_count"], 0)

            manager.mark_replay_attempt("A2")
            filing_after = manager.get_filing("A2")
            self.assertEqual(filing_after["replay_count"], 1)
            self.assertTrue(bool(filing_after["last_replay_at"]))

    def test_watchlist_and_notifications(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "state.db")
            manager = StateManager(db_path=db_path)

            manager.add_watchlist_ticker("o1", "u1", "MSFT")
            manager.add_watchlist_ticker("o1", "u1", "AAPL")
            watchlist = manager.list_watchlist("o1", "u1")
            self.assertEqual([item["ticker"] for item in watchlist], ["AAPL", "MSFT"])

            subscribers = manager.list_watchlist_subscribers("o1", "msft")
            self.assertEqual(subscribers, ["u1"])

            manager.create_notification(
                org_id="o1",
                user_id="u1",
                ticker="MSFT",
                accession_number="A1",
                notification_type="FILING_FOUND",
                title="New MSFT filing detected",
                body="body",
            )
            notifications = manager.list_notifications("o1", "u1", limit=10, unread_only=True)
            self.assertEqual(len(notifications), 1)
            self.assertFalse(notifications[0]["is_read"])

            updated = manager.mark_notification_read("o1", "u1", notifications[0]["id"])
            self.assertTrue(updated)
            unread = manager.list_notifications("o1", "u1", limit=10, unread_only=True)
            self.assertEqual(len(unread), 0)

    def test_event_activity_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "state.db")
            manager = StateManager(db_path=db_path)
            manager.log_event("INGESTION_CYCLE", "test", "{}")
            manager.log_event("INGESTION_CYCLE", "test", "{}")
            manager.log_event("ANALYSIS_SUCCESS", "test", "{}")
            counts = manager.count_recent_events(minutes=60)
            self.assertEqual(counts.get("INGESTION_CYCLE"), 2)
            self.assertEqual(counts.get("ANALYSIS_SUCCESS"), 1)

    def test_ask_templates_and_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "state.db")
            manager = StateManager(db_path=db_path)
            templates = manager.list_ask_templates("o1", "u1")
            self.assertGreaterEqual(len(templates), 1)
            template_id = templates[0]["id"]
            rules = manager.list_ask_template_rules(template_id)
            self.assertGreaterEqual(len(rules), 1)

            run_id = manager.create_ask_template_run(
                org_id="o1",
                user_id="u1",
                template_id=template_id,
                ticker="MSFT",
                rendered_question="What changed for MSFT?",
                relevance_label="High relevance",
                coverage_brief="Based on analyzed filings: 10-Q (2026-01-01).",
                answer_markdown="Answer",
                citations=["chunk-1"],
                confidence=0.78,
                derivation_trace=["Used Q4 revenue and prior quarter revenue", "Computed growth percentage"],
                latency_ms=123,
            )
            self.assertGreater(run_id, 0)
            runs = manager.list_ask_template_runs("o1", "u1", limit=5)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["relevance_label"], "High relevance")
            self.assertAlmostEqual(runs[0]["confidence"], 0.78, places=2)
            self.assertEqual(len(runs[0]["derivation_trace"]), 2)


if __name__ == "__main__":
    unittest.main()
