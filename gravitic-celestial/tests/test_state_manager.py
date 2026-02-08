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


if __name__ == "__main__":
    unittest.main()
