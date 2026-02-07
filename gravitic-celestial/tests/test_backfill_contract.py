"""Unit tests for backfill API/worker shared contract."""

import unittest
from unittest.mock import MagicMock, patch

from services.backfill import run_backfill


class _Record(object):
    def __init__(self, ticker, accession):
        self.ticker = ticker
        self.accession_number = accession
        self.filing_url = "http://%s" % accession
        self.metadata = {}


class _Edgar(object):
    def get_recent_filings(self, tickers, per_ticker_limit=8):
        _ = per_ticker_limit
        rows = []
        if "MSFT" in tickers:
            rows.append(_Record("MSFT", "A1"))
            rows.append(_Record("MSFT", "A2"))
        return rows

    def get_filing_text(self, record):
        return "long text " * 200 if record.accession_number == "A1" else "short"

    def get_filing_attachments(self, record):
        _ = record
        return []

    def find_exhibit_991_text(self, attachments):
        _ = attachments
        return None


class _GraphRuntime(object):
    def __init__(self):
        self.ingestion_nodes = type("Nodes", (), {"edgar_client": _Edgar()})()

    def analyze_filing(self, payload):
        return payload

    def index_analysis(self, analysis):
        _ = analysis
        return {"ok": True}


class BackfillContractTests(unittest.TestCase):
    def test_skips_existing_and_supports_notification_scope(self):
        state_manager = MagicMock()
        state_manager.has_accession.side_effect = lambda acc: acc == "A2"
        graph_runtime = _GraphRuntime()

        with patch("services.backfill.create_filing_notifications", return_value=1) as create_notifs:
            result = run_backfill(
                graph_runtime,
                state_manager,
                {
                    "tickers": ["MSFT"],
                    "include_existing": False,
                    "notify": True,
                    "org_id": "o1",
                    "per_ticker_limit": 8,
                },
            )

        self.assertEqual(result["records_found"], 2)
        self.assertEqual(result["filings_processed"], 1)
        self.assertEqual(result["analyzed"], 1)
        self.assertEqual(result["indexed"], 1)
        create_notifs.assert_called_once()
        self.assertEqual(create_notifs.call_args[1]["org_id"], "o1")


if __name__ == "__main__":
    unittest.main()
