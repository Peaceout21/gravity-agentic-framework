"""Tests for FastAPI endpoints using TestClient with mocked backends."""

import unittest
from unittest.mock import MagicMock, patch


class ApiEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("fastapi not installed")

    def _make_client(self, mock_components=None):
        from fastapi.testclient import TestClient
        from services.api import app, _runtime_cache

        _runtime_cache.clear()
        if mock_components:
            _runtime_cache.update(mock_components)

        return TestClient(app)

    def _auth_headers(self, org_id="default-org", user_id="default-user", api_key=None):
        headers = {
            "X-Org-Id": org_id,
            "X-User-Id": user_id,
        }
        if api_key:
            headers["X-API-Key"] = api_key
        return headers

    def _default_mocks(self):
        state_manager = MagicMock()
        state_manager.list_recent_filings.return_value = [
            {
                "accession_number": "0001-23-000001",
                "ticker": "MSFT",
                "filing_url": "http://sec.gov/test",
                "status": "ANALYZED",
                "dead_letter_reason": "",
                "last_error": "",
                "replay_count": 0,
                "last_replay_at": "",
                "updated_at": "2025-01-01T00:00:00",
            }
        ]
        state_manager.get_filing.return_value = {
            "accession_number": "0001-23-000001",
            "ticker": "MSFT",
            "filing_url": "http://sec.gov/test",
            "status": "DEAD_LETTER",
            "market": "US_SEC",
        }
        state_manager.list_watchlist.return_value = [{"ticker": "MSFT", "created_at": "2025-01-01T00:00:00"}]
        state_manager.list_notifications.return_value = [
            {
                "id": 1,
                "org_id": "default-org",
                "user_id": "default",
                "ticker": "MSFT",
                "accession_number": "0001-23-000001",
                "notification_type": "FILING_FOUND",
                "title": "New MSFT filing detected",
                "body": "body",
                "is_read": False,
                "created_at": "2025-01-01T00:00:00",
            }
        ]
        state_manager.mark_notification_read.return_value = True
        state_manager.list_ask_templates.return_value = [
            {
                "id": 1,
                "template_key": "qoq_changes",
                "title": "Quarter-over-quarter changes",
                "description": "Summarize quarter changes",
                "category": "overview",
                "question_template": "What changed for {ticker}?",
                "requires_ticker": True,
                "enabled": True,
                "sort_order": 10,
            }
        ]
        state_manager.get_ask_template.return_value = {
            "id": 1,
            "template_key": "qoq_changes",
            "title": "Quarter-over-quarter changes",
            "description": "Summarize quarter changes",
            "category": "overview",
            "question_template": "What changed for {ticker}?",
            "requires_ticker": True,
            "enabled": True,
            "sort_order": 10,
        }
        state_manager.list_recent_analyzed_filings.return_value = [
            {
                "accession_number": "A1",
                "ticker": "MSFT",
                "filing_type": "10-Q",
                "item_code": "",
                "filing_date": "2026-01-01",
                "updated_at": "2026-01-01T00:00:00",
                "status": "ANALYZED",
                "filing_url": "http://sec.gov/a1",
            }
        ]
        state_manager.list_ask_template_rules.return_value = [{"filing_type": "10-Q", "item_code": "", "weight": 1.0}]
        state_manager.create_ask_template_run.return_value = 1001
        state_manager.list_ask_template_runs.return_value = []

        graph_runtime = MagicMock()
        graph_runtime.run_ingestion_cycle.return_value = []
        provider = MagicMock()
        provider.market_code = "US_SEC"
        provider.resolve_instrument.return_value = {"ticker": "MSFT", "issuer_id": "0000789019", "exchange": "SEC"}
        graph_runtime.ingestion_nodes.edgar_client = provider

        answer_mock = MagicMock()
        answer_mock.question = "test?"
        answer_mock.answer_markdown = "Test answer."
        answer_mock.citations = ["chunk-1"]
        answer_mock.confidence = 0.74
        answer_mock.derivation_trace = ["Used latest filing summary"]
        graph_runtime.answer_question.return_value = answer_mock
        graph_runtime.replay_filing.return_value = {
            "status": "ok",
            "accession_number": "0001-23-000001",
            "mode": "analysis",
            "analyzed": True,
            "indexed": True,
        }

        return {
            "state_manager": state_manager,
            "rag_engine": MagicMock(),
            "job_queue": None,
            "graph_runtime": graph_runtime,
            "supported_markets": ["US_SEC"],
            "provider_factory": MagicMock(),
            "sec_identity": "Unknown unknown@example.com",
        }

    def test_health_ok(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["database"], "ok")
        self.assertEqual(data["redis"], "not_configured")

    def test_health_with_redis(self):
        mocks = self._default_mocks()
        job_queue = MagicMock()
        job_queue.ping.return_value = True
        mocks["job_queue"] = job_queue

        client = self._make_client(mocks)
        resp = client.get("/health")
        data = resp.json()
        self.assertEqual(data["redis"], "ok")

    def test_filings_returns_list(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        resp = client.get("/filings", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["ticker"], "MSFT")

    def test_filings_scoped_to_watchlist(self):
        mocks = self._default_mocks()
        mocks["state_manager"].list_recent_filings.return_value = [
            {
                "accession_number": "A1",
                "ticker": "AAPL",
                "filing_url": "http://sec.gov/a",
                "status": "ANALYZED",
                "dead_letter_reason": "",
                "last_error": "",
                "replay_count": 0,
                "last_replay_at": "",
                "updated_at": "2025-01-01T00:00:00",
            }
        ]
        client = self._make_client(mocks)
        resp = client.get("/filings", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_markets_returns_supported_list(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        resp = client.get("/markets")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["markets"], ["US_SEC"])

    def test_resolve_instrument(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        resp = client.get("/instruments/resolve", params={"ticker": "MSFT", "market": "US_SEC"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["ticker"], "MSFT")
        self.assertEqual(body["issuer_id"], "0000789019")

    def test_ingest_sync_mode(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        with patch("services.notifications.create_filing_notifications", return_value=0) as create_notifications:
            resp = client.post("/ingest", json={"tickers": ["AAPL"]}, headers=self._auth_headers())
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["mode"], "sync")
            self.assertEqual(data["filings_processed"], 0)
            create_notifications.assert_called_once_with(mocks["state_manager"], [], org_id="default-org")

    def test_ingest_async_mode(self):
        mocks = self._default_mocks()
        job_queue = MagicMock()
        job_queue.enqueue_ingestion.return_value = "job-123"
        mocks["job_queue"] = job_queue

        client = self._make_client(mocks)
        resp = client.post("/ingest", json={"tickers": ["MSFT"]}, headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["mode"], "async")
        self.assertEqual(data["job_id"], "job-123")

    def test_ingest_empty_tickers_returns_400(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        resp = client.post("/ingest", json={"tickers": []}, headers=self._auth_headers())
        self.assertEqual(resp.status_code, 400)

    def test_ingest_rejects_unsupported_market(self):
        mocks = self._default_mocks()
        mocks["graph_runtime"].ingestion_nodes.edgar_client.market_code = "US_SEC"
        client = self._make_client(mocks)
        resp = client.post("/ingest", json={"tickers": ["MSFT"], "market": "IN_NSE"}, headers=self._auth_headers())
        self.assertEqual(resp.status_code, 400)

    def test_query_returns_answer(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        resp = client.post("/query", json={"question": "What was MSFT revenue?"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["answer_markdown"], "Test answer.")
        self.assertEqual(data["citations"], ["chunk-1"])
        self.assertAlmostEqual(data["confidence"], 0.74, places=2)
        self.assertEqual(data["derivation_trace"], ["Used latest filing summary"])

    def test_query_empty_question_returns_400(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        resp = client.post("/query", json={"question": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_replay_filing_success(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        resp = client.post(
            "/filings/replay",
            json={"accession_number": "0001-23-000001", "mode": "analysis"},
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["accession_number"], "0001-23-000001")
        mocks["graph_runtime"].replay_filing.assert_called_once_with("0001-23-000001", mode="analysis")

    def test_replay_filing_not_found(self):
        mocks = self._default_mocks()
        mocks["state_manager"].get_filing.return_value = None
        client = self._make_client(mocks)
        resp = client.post(
            "/filings/replay",
            json={"accession_number": "does-not-exist"},
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 404)

    def test_replay_filing_forbidden_outside_watchlist(self):
        mocks = self._default_mocks()
        mocks["state_manager"].get_filing.return_value = {
            "accession_number": "0001-23-000001",
            "ticker": "AAPL",
            "filing_url": "http://sec.gov/test",
            "status": "DEAD_LETTER",
            "market": "US_SEC",
        }
        client = self._make_client(mocks)
        resp = client.post(
            "/filings/replay",
            json={"accession_number": "0001-23-000001", "mode": "analysis"},
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 403)

    def test_watchlist_add_and_list(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        add_resp = client.post("/watchlist", json={"tickers": ["MSFT"]}, headers=self._auth_headers())
        self.assertEqual(add_resp.status_code, 200)
        list_resp = client.get("/watchlist", headers=self._auth_headers())
        self.assertEqual(list_resp.status_code, 200)
        data = list_resp.json()
        self.assertEqual(data[0]["ticker"], "MSFT")
        self.assertEqual(data[0]["market"], "US_SEC")

    def test_watchlist_remove(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        resp = client.request("DELETE", "/watchlist", json={"tickers": ["MSFT"]}, headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)

    def test_watchlist_add_for_market(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        resp = client.post(
            "/watchlist",
            json={"tickers": ["INFY"], "market": "IN_NSE", "exchange": "NSE"},
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 200)
        mocks["state_manager"].add_watchlist_ticker.assert_called_once_with(
            org_id="default-org",
            user_id="default-user",
            ticker="INFY",
            market="IN_NSE",
            exchange="NSE",
        )

    def test_notifications_list_and_mark_read(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        list_resp = client.get("/notifications", headers=self._auth_headers())
        self.assertEqual(list_resp.status_code, 200)
        data = list_resp.json()
        self.assertEqual(len(data), 1)
        self.assertFalse(data[0]["is_read"])

        read_resp = client.post("/notifications/1/read", json={}, headers=self._auth_headers())
        self.assertEqual(read_resp.status_code, 200)

    def test_backfill_async_mode(self):
        mocks = self._default_mocks()
        job_queue = MagicMock()
        job_queue.enqueue_backfill.return_value = "backfill-123"
        mocks["job_queue"] = job_queue
        client = self._make_client(mocks)

        resp = client.post(
            "/backfill",
            json={"tickers": ["MSFT"], "per_ticker_limit": 6, "include_existing": False, "notify": True},
            headers=self._auth_headers(org_id="o2", user_id="u2"),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["mode"], "async")
        self.assertEqual(data["job_id"], "backfill-123")
        queued_payload = job_queue.enqueue_backfill.call_args[0][0]
        self.assertEqual(queued_payload["org_id"], "o2")
        self.assertEqual(queued_payload["tickers"], ["MSFT"])

    def test_backfill_sync_mode(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        with patch(
            "services.backfill.run_backfill",
            return_value={"filings_processed": 3, "analyzed": 3, "indexed": 2},
        ) as run_backfill:
            resp = client.post(
                "/backfill",
                json={"tickers": ["MSFT"], "per_ticker_limit": 4, "include_existing": True, "notify": False},
                headers=self._auth_headers(org_id="o3"),
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["mode"], "sync")
            payload = run_backfill.call_args[0][2]
            self.assertEqual(payload["org_id"], "o3")

    def test_backfill_rejects_unsupported_market(self):
        mocks = self._default_mocks()
        mocks["graph_runtime"].ingestion_nodes.edgar_client.market_code = "US_SEC"
        client = self._make_client(mocks)
        resp = client.post(
            "/backfill",
            json={"tickers": ["MSFT"], "market": "IN_BSE"},
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_auth_api_key_enforced(self):
        mocks = self._default_mocks()
        with patch.dict("os.environ", {"GRAVITY_API_KEY": "secret-key"}):
            client = self._make_client(mocks)
            unauthorized = client.post("/ingest", json={"tickers": ["MSFT"]}, headers=self._auth_headers())
            self.assertEqual(unauthorized.status_code, 401)
            authorized = client.post(
                "/ingest",
                json={"tickers": ["MSFT"]},
                headers=self._auth_headers(api_key="secret-key"),
            )
            self.assertEqual(authorized.status_code, 200)

    def test_read_all_notifications(self):
        mocks = self._default_mocks()
        mocks["state_manager"].mark_all_notifications_read.return_value = 5
        client = self._make_client(mocks)
        resp = client.post(
            "/notifications/read-all",
            json={"ticker": "MSFT"},
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["updated"], 5)
        mocks["state_manager"].mark_all_notifications_read.assert_called_once_with(
            org_id="default-org",
            user_id="default-user",
            ticker="MSFT",
            notification_type=None,
            before=None,
        )

    def test_unread_notification_count(self):
        mocks = self._default_mocks()
        mocks["state_manager"].count_unread_notifications.return_value = 12
        client = self._make_client(mocks)
        resp = client.get("/notifications/count", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["unread"], 12)

    def test_ticker_count_scoped_to_watchlist(self):
        mocks = self._default_mocks()
        mocks["state_manager"].count_filings_for_ticker.return_value = 7
        client = self._make_client(mocks)

        resp_allowed = client.get("/filings/ticker-count", params={"ticker": "MSFT"}, headers=self._auth_headers())
        self.assertEqual(resp_allowed.status_code, 200)
        self.assertEqual(resp_allowed.json()["count"], 7)

        resp_denied = client.get("/filings/ticker-count", params={"ticker": "AAPL"}, headers=self._auth_headers())
        self.assertEqual(resp_denied.status_code, 200)
        self.assertEqual(resp_denied.json()["count"], 0)

    def test_ops_health(self):
        mocks = self._default_mocks()
        job_queue = MagicMock()
        job_queue.ping.return_value = True
        job_queue.worker_count.return_value = 3
        mocks["job_queue"] = job_queue
        client = self._make_client(mocks)
        resp = client.get("/ops/health", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["api"], "ok")
        self.assertEqual(data["db"], "ok")
        self.assertEqual(data["redis"], "ok")
        self.assertEqual(data["workers"], 3)

    def test_ops_metrics(self):
        mocks = self._default_mocks()
        mocks["state_manager"].count_filings_by_status.return_value = {"ANALYZED": 10, "INGESTED": 5}
        mocks["state_manager"].count_recent_events.return_value = {"FILING_FOUND": 3}
        mocks["state_manager"].list_recent_failures.return_value = []
        job_queue = MagicMock()
        job_queue.queue_depths.return_value = {"ingestion": 2, "analysis": 0}
        job_queue.failed_job_count.return_value = 1
        mocks["job_queue"] = job_queue
        client = self._make_client(mocks)
        resp = client.get("/ops/metrics", params={"window_minutes": 30}, headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["queue_depths"]["ingestion"], 2)
        self.assertEqual(data["filing_status_counts"]["ANALYZED"], 10)
        self.assertEqual(data["failed_jobs"], 1)

    def test_notifications_filter_params_forwarded(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        resp = client.get(
            "/notifications",
            params={"limit": 10, "unread_only": True, "ticker": "MSFT", "notification_type": "FILING_FOUND"},
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 200)
        mocks["state_manager"].list_notifications.assert_called_once_with(
            org_id="default-org",
            user_id="default-user",
            limit=10,
            unread_only=True,
            ticker="MSFT",
            notification_type="FILING_FOUND",
        )

    def test_list_ask_templates(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        resp = client.get("/ask/templates", headers=self._auth_headers(org_id="o1", user_id="u1"))
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertEqual(rows[0]["template_key"], "qoq_changes")
        mocks["state_manager"].list_ask_templates.assert_called_once_with(org_id="o1", user_id="u1")

    def test_template_run_success(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        resp = client.post(
            "/ask/template-run",
            json={"template_id": 1, "ticker": "MSFT"},
            headers=self._auth_headers(org_id="o1", user_id="u1"),
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["template_id"], 1)
        self.assertEqual(payload["relevance_label"], "High relevance")
        self.assertTrue(payload["answer_markdown"])

    def test_template_run_requires_ticker(self):
        mocks = self._default_mocks()
        client = self._make_client(mocks)
        resp = client.post(
            "/ask/template-run",
            json={"template_id": 1},
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
