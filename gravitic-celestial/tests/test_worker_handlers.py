"""Unit tests for worker handler chaining and fallback behavior."""

import unittest
from unittest.mock import MagicMock, patch

from services import worker


class DummyPayload(object):
    def __init__(self, data):
        self._data = data

    def dict(self):
        return dict(self._data)


class WorkerHandlerTests(unittest.TestCase):
    def setUp(self):
        worker._worker_cache.clear()

    def test_handle_ingestion_enqueues_analysis_jobs(self):
        mock_runtime = MagicMock()
        mock_runtime.run_ingestion_cycle.return_value = [
            DummyPayload({"ticker": "MSFT", "accession_number": "A1", "filing_url": "u1", "raw_text": "x", "metadata": {}}),
            DummyPayload({"ticker": "AAPL", "accession_number": "A2", "filing_url": "u2", "raw_text": "y", "metadata": {}}),
        ]
        mock_queue = MagicMock()

        mock_state_manager = MagicMock()
        worker._worker_cache["backends"] = {"state_manager": mock_state_manager}

        with patch.object(worker, "_get_runtime", return_value=mock_runtime), patch.object(
            worker, "_get_job_queue", return_value=mock_queue
        ), patch("services.notifications.create_filing_notifications", return_value=2) as create_notifications:
            result = worker.handle_ingestion(["MSFT", "AAPL"])

        self.assertEqual(result["filings_found"], 2)
        self.assertEqual(mock_queue.enqueue_analysis.call_count, 2)
        create_notifications.assert_called_once_with(
            mock_state_manager, mock_runtime.run_ingestion_cycle.return_value, org_id="default"
        )

    def test_handle_ingestion_sync_fallback_without_queue(self):
        mock_runtime = MagicMock()
        mock_runtime.run_ingestion_cycle.return_value = [
            DummyPayload({"ticker": "MSFT", "accession_number": "A1", "filing_url": "u1", "raw_text": "x", "metadata": {}})
        ]

        mock_state_manager = MagicMock()
        worker._worker_cache["backends"] = {"state_manager": mock_state_manager}

        with patch.object(worker, "_get_runtime", return_value=mock_runtime), patch.object(
            worker, "_get_job_queue", return_value=None
        ), patch.object(worker, "_handle_analysis_sync", return_value={"status": "analyzed"}) as fallback, patch(
            "services.notifications.create_filing_notifications", return_value=1
        ) as create_notifications:
            result = worker.handle_ingestion(["MSFT"])

        self.assertEqual(result["filings_found"], 1)
        fallback.assert_called_once()
        create_notifications.assert_called_once_with(
            mock_state_manager, mock_runtime.run_ingestion_cycle.return_value, org_id="default"
        )

    def test_handle_ingestion_accepts_market_payload(self):
        mock_runtime = MagicMock()
        mock_runtime.run_ingestion_cycle.return_value = []
        mock_state_manager = MagicMock()
        worker._worker_cache["backends"] = {"state_manager": mock_state_manager}

        with patch.object(worker, "_get_runtime", return_value=mock_runtime), patch.object(
            worker, "_get_job_queue", return_value=MagicMock()
        ), patch("services.notifications.create_filing_notifications", return_value=0):
            result = worker.handle_ingestion({"tickers": ["MSFT"], "market": "US_SEC", "exchange": "SEC"})

        self.assertEqual(result["filings_found"], 0)
        mock_runtime.run_ingestion_cycle.assert_called_once_with(["MSFT"], market="US_SEC", exchange="SEC")

    def test_handle_analysis_enqueues_knowledge_when_analysis_succeeds(self):
        mock_runtime = MagicMock()
        mock_analysis = DummyPayload(
            {
                "ticker": "MSFT",
                "accession_number": "A1",
                "kpis": [{"metric": "Revenue", "value": "10"}],
                "summary": {"highlights": ["h1"]},
                "guidance": [],
            }
        )
        mock_runtime.analyze_filing.return_value = mock_analysis
        mock_queue = MagicMock()

        filing_payload = {
            "ticker": "MSFT",
            "accession_number": "A1",
            "filing_url": "u1",
            "raw_text": "text",
            "metadata": {},
        }

        with patch.object(worker, "_get_runtime", return_value=mock_runtime), patch.object(
            worker, "_get_job_queue", return_value=mock_queue
        ):
            result = worker.handle_analysis(filing_payload)

        self.assertEqual(result["status"], "analyzed")
        mock_queue.enqueue_knowledge.assert_called_once()

    def test_handle_analysis_returns_dead_letter_when_analysis_fails(self):
        mock_runtime = MagicMock()
        mock_runtime.analyze_filing.return_value = None

        filing_payload = {
            "ticker": "MSFT",
            "accession_number": "A1",
            "filing_url": "u1",
            "raw_text": "text",
            "metadata": {},
        }

        with patch.object(worker, "_get_runtime", return_value=mock_runtime), patch.object(
            worker, "_get_job_queue", return_value=MagicMock()
        ) as mock_queue:
            result = worker.handle_analysis(filing_payload)

        self.assertEqual(result["status"], "dead_letter")
        mock_queue.enqueue_knowledge.assert_not_called()

    def test_handle_analysis_sync_fallback_calls_handle_knowledge(self):
        mock_runtime = MagicMock()
        mock_analysis = DummyPayload(
            {
                "ticker": "MSFT",
                "accession_number": "A1",
                "kpis": [{"metric": "Revenue", "value": "10"}],
                "summary": {"highlights": ["h1"]},
                "guidance": [],
            }
        )
        mock_runtime.analyze_filing.return_value = mock_analysis

        filing_payload = {
            "ticker": "MSFT",
            "accession_number": "A1",
            "filing_url": "u1",
            "raw_text": "text",
            "metadata": {},
        }

        with patch.object(worker, "_get_runtime", return_value=mock_runtime), patch.object(
            worker, "_get_job_queue", return_value=None
        ), patch.object(worker, "handle_knowledge", return_value={"status": "indexed"}) as handle_knowledge:
            result = worker.handle_analysis(filing_payload)

        self.assertEqual(result["status"], "analyzed")
        handle_knowledge.assert_called_once()

    def test_handle_backfill_invokes_shared_runner(self):
        mock_runtime = MagicMock()
        mock_state_manager = MagicMock()
        worker._worker_cache["backends"] = {"state_manager": mock_state_manager}
        backfill_request = {"tickers": ["MSFT"], "org_id": "o1", "notify": True}

        with patch.object(worker, "_get_runtime", return_value=mock_runtime), patch(
            "services.backfill.run_backfill",
            return_value={"filings_processed": 1, "analyzed": 1, "indexed": 1},
        ) as run_backfill:
            result = worker.handle_backfill(backfill_request)

        self.assertEqual(result["filings_processed"], 1)
        run_backfill.assert_called_once_with(mock_runtime, mock_state_manager, backfill_request)


if __name__ == "__main__":
    unittest.main()
