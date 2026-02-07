import os
import tempfile
import unittest

from core.framework.state_manager import StateManager
from core.graph.nodes.ingestion_node import IngestionNodes
from core.tools.edgar_client import FilingRecord


class Provider(object):
    def get_latest_filings(self, tickers):
        return [
            FilingRecord(ticker="MSFT", accession_number="A1", filing_url="http://sec/A1"),
            FilingRecord(ticker="MSFT", accession_number="A2", filing_url="http://sec/A2"),
        ]


class IngestionDedupeTests(unittest.TestCase):
    def test_existing_accession_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = StateManager(db_path=os.path.join(tmpdir, "state.db"))
            manager.mark_ingested("A1", "MSFT", "http://sec/A1")

            nodes = IngestionNodes(edgar_client=Provider(), state_manager=manager, tickers=["MSFT"])
            state = nodes.poll_edgar({})
            queue = state.get("filings_queue", [])
            accessions = [item["accession_number"] for item in queue]
            self.assertEqual(accessions, ["A2"])


if __name__ == "__main__":
    unittest.main()
