"""Deterministic seeded E2E for watchlist -> backfill -> in-app notifications."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock

from core.framework.state_manager import StateManager


class _FakeRecord(object):
    def __init__(self, ticker, accession_number, filing_url):
        self.ticker = ticker
        self.accession_number = accession_number
        self.filing_url = filing_url
        self.metadata = {"seeded": True}


class _FakeEdgarClient(object):
    def get_recent_filings(self, tickers, per_ticker_limit=8):
        _ = per_ticker_limit
        if "MSFT" not in tickers:
            return []
        return [_FakeRecord("MSFT", "SEED-0001", "http://seeded-filing")]

    def get_filing_text(self, filing_record):
        _ = filing_record
        return "seeded filing text " * 90

    def get_filing_attachments(self, filing_record):
        _ = filing_record
        return []

    def find_exhibit_991_text(self, attachments):
        _ = attachments
        return None


class _FakeGraphRuntime(object):
    def __init__(self):
        self.ingestion_nodes = type("Nodes", (), {"edgar_client": _FakeEdgarClient()})()

    def analyze_filing(self, payload):
        return {"accession_number": payload.accession_number}

    def index_analysis(self, analysis_payload):
        _ = analysis_payload
        return {"indexed": True}


class NotificationSeededE2ETests(unittest.TestCase):
    def _auth_headers(self, org_id, user_id):
        return {"X-Org-Id": org_id, "X-User-Id": user_id}

    def test_seeded_backfill_generates_org_scoped_notifications(self):
        from fastapi.testclient import TestClient
        from services.api import _runtime_cache, app

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "seeded_state.db")
            state_manager = StateManager(db_path=db_path)
            _runtime_cache.clear()
            _runtime_cache.update(
                {
                    "state_manager": state_manager,
                    "rag_engine": MagicMock(),
                    "job_queue": None,
                    "graph_runtime": _FakeGraphRuntime(),
                }
            )

            client = TestClient(app)

            add_a = client.post(
                "/watchlist",
                json={"tickers": ["MSFT"]},
                headers=self._auth_headers("org-a", "alice"),
            )
            self.assertEqual(add_a.status_code, 200)

            add_b = client.post(
                "/watchlist",
                json={"tickers": ["MSFT"]},
                headers=self._auth_headers("org-b", "bob"),
            )
            self.assertEqual(add_b.status_code, 200)

            backfill = client.post(
                "/backfill",
                json={"tickers": ["MSFT"], "per_ticker_limit": 4, "include_existing": False, "notify": True},
                headers=self._auth_headers("org-a", "alice"),
            )
            self.assertEqual(backfill.status_code, 200)
            self.assertEqual(backfill.json()["mode"], "sync")

            org_a_notifs = client.get(
                "/notifications",
                params={"unread_only": True},
                headers=self._auth_headers("org-a", "alice"),
            )
            self.assertEqual(org_a_notifs.status_code, 200)
            rows_a = org_a_notifs.json()
            self.assertEqual(len(rows_a), 1)
            self.assertEqual(rows_a[0]["ticker"], "MSFT")
            self.assertEqual(rows_a[0]["accession_number"], "SEED-0001")

            org_b_notifs = client.get(
                "/notifications",
                params={"unread_only": True},
                headers=self._auth_headers("org-b", "bob"),
            )
            self.assertEqual(org_b_notifs.status_code, 200)
            self.assertEqual(len(org_b_notifs.json()), 0)


if __name__ == "__main__":
    unittest.main()
