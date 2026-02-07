import unittest
import os
import tempfile

from core.framework.state_manager import StateManager
from core.graph.nodes.ingestion_node import IngestionNodes
from core.tools.edgar_client import AttachmentRecord, FilingRecord


class FakeEdgar(object):
    def get_latest_filings(self, tickers):
        return [FilingRecord(ticker="MSFT", accession_number="0001", filing_url="https://sec.test/1")]

    def get_filing_text(self, filing_record):
        return "cover"

    def get_filing_attachments(self, filing_record):
        return [AttachmentRecord(name="ex99.1", description="Press Release", text="Revenue was $50B")]

    @staticmethod
    def find_exhibit_991_text(attachments):
        for item in attachments:
            if "99.1" in item.name.lower() or "press release" in item.description.lower():
                return item.text
        return None


class ExhibitFallbackTests(unittest.TestCase):
    def test_exhibit_is_merged_when_primary_text_short(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_manager = StateManager(db_path=os.path.join(tmpdir, "state.db"))
            nodes = IngestionNodes(edgar_client=FakeEdgar(), state_manager=state_manager, tickers=["MSFT"])

            state = nodes.poll_edgar({})
            state.update(nodes.fetch_full_text(state))
            self.assertEqual(nodes.route_exhibit_logic(state), "fetch_exhibits")
            state.update(nodes.fetch_exhibits(state))
            state.update(nodes.merge_text(state))

            self.assertIn("Revenue was $50B", state["raw_text"])


if __name__ == "__main__":
    unittest.main()
