"""Tests for the HTTP API client wrapper."""

import json
import unittest
from unittest.mock import MagicMock, patch


class GravityApiClientTests(unittest.TestCase):
    def _make_client(self):
        from ui.api_client import GravityApiClient
        client = GravityApiClient("http://localhost:8000", org_id="org-1", user_id="u-1", api_key="k-1")
        client._session = MagicMock()
        return client

    def _mock_response(self, data, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = data
        resp.raise_for_status.return_value = None
        return resp

    def test_health(self):
        client = self._make_client()
        client._session.get.return_value = self._mock_response(
            {"status": "ok", "database": "ok", "redis": "ok"}
        )
        result = client.health()
        self.assertEqual(result["status"], "ok")
        client._session.get.assert_called_once()

    def test_list_filings(self):
        client = self._make_client()
        client._session.get.return_value = self._mock_response([
            {"accession_number": "A1", "ticker": "MSFT", "filing_url": "http://x", "status": "ANALYZED", "updated_at": "2025-01-01"}
        ])
        result = client.list_filings(limit=10)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ticker"], "MSFT")

    def test_ingest(self):
        client = self._make_client()
        client._session.post.return_value = self._mock_response(
            {"mode": "async", "job_id": "j-1", "filings_processed": None}
        )
        result = client.ingest(["MSFT", "AAPL"])
        self.assertEqual(result["mode"], "async")
        call_args = client._session.post.call_args
        self.assertIn("ingest", call_args[0][0])
        self.assertEqual(call_args[1]["headers"]["X-Org-Id"], "org-1")
        self.assertEqual(call_args[1]["headers"]["X-User-Id"], "u-1")
        self.assertEqual(call_args[1]["headers"]["X-API-Key"], "k-1")

    def test_backfill(self):
        client = self._make_client()
        client._session.post.return_value = self._mock_response(
            {"mode": "async", "job_id": "b-1"}
        )
        result = client.backfill(["MSFT"], per_ticker_limit=12, include_existing=True, notify=True)
        self.assertEqual(result["job_id"], "b-1")
        call_args = client._session.post.call_args
        self.assertIn("backfill", call_args[0][0])
        self.assertEqual(call_args[1]["json"]["per_ticker_limit"], 12)
        self.assertTrue(call_args[1]["json"]["include_existing"])
        self.assertTrue(call_args[1]["json"]["notify"])

    def test_query(self):
        client = self._make_client()
        client._session.post.return_value = self._mock_response(
            {"question": "test?", "answer_markdown": "Answer.", "citations": []}
        )
        result = client.query("test?")
        self.assertEqual(result["answer_markdown"], "Answer.")

    def test_query_with_ticker(self):
        client = self._make_client()
        client._session.post.return_value = self._mock_response(
            {"question": "test?", "answer_markdown": "Answer.", "citations": []}
        )
        result = client.query("test?", ticker="MSFT")
        call_args = client._session.post.call_args
        body = call_args[1]["json"]
        self.assertEqual(body["ticker"], "MSFT")

    def test_watchlist_methods(self):
        client = self._make_client()
        client._session.get.return_value = self._mock_response(
            [{"ticker": "MSFT", "created_at": "2025-01-01T00:00:00"}]
        )
        client._session.post.return_value = self._mock_response({"status": "ok"})
        client._session.request.return_value = self._mock_response({"status": "ok"})

        watchlist = client.list_watchlist(user_id="u1")
        self.assertEqual(watchlist[0]["ticker"], "MSFT")
        add_result = client.add_watchlist(["MSFT"], user_id="u1")
        self.assertEqual(add_result["status"], "ok")
        remove_result = client.remove_watchlist(["MSFT"], user_id="u1")
        self.assertEqual(remove_result["status"], "ok")
        self.assertEqual(client._session.get.call_args[1]["headers"]["X-Org-Id"], "org-1")

    def test_notification_methods(self):
        client = self._make_client()
        client._session.get.return_value = self._mock_response(
            [{"id": 1, "title": "New MSFT filing detected", "is_read": False}]
        )
        client._session.post.return_value = self._mock_response({"status": "ok"})

        rows = client.list_notifications(user_id="u1", unread_only=True)
        self.assertEqual(rows[0]["id"], 1)
        result = client.mark_notification_read(1, user_id="u1")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(client._session.post.call_args[1]["headers"]["X-User-Id"], "u-1")

    def test_notification_filter_params(self):
        client = self._make_client()
        client._session.get.return_value = self._mock_response([])
        _ = client.list_notifications(limit=25, unread_only=True, ticker="msft", notification_type="FILING_FOUND")
        params = client._session.get.call_args[1]["params"]
        self.assertEqual(params["ticker"], "MSFT")
        self.assertEqual(params["notification_type"], "FILING_FOUND")

    def test_ops_methods_include_auth_headers(self):
        client = self._make_client()
        client._session.get.return_value = self._mock_response({"ok": True})
        client.ops_health()
        self.assertEqual(client._session.get.call_args[1]["headers"]["X-Org-Id"], "org-1")
        client.ops_metrics(window_minutes=30)
        self.assertEqual(client._session.get.call_args[1]["headers"]["X-User-Id"], "u-1")


if __name__ == "__main__":
    unittest.main()
