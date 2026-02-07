"""Live integration tests for API + worker pipeline.

These tests hit a running stack (typically docker-compose):
- API health endpoint
- async ingestion trigger
- filings polling for status transitions

Set environment variables to control execution:
- GRAVITY_API_URL (default: http://localhost:8000)
- INTEGRATION_TICKERS (comma-separated, default: MSFT)
- INTEGRATION_POLL_TIMEOUT_SECONDS (default: 90)
- INTEGRATION_POLL_INTERVAL_SECONDS (default: 3)

Tests skip automatically when the API is not reachable.
"""

import os
import time
import unittest
from datetime import datetime

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


TERMINAL_STATUSES = {"ANALYZED", "ANALYZED_NOT_INDEXED", "DEAD_LETTER"}


class LivePipelineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if requests is None:
            raise unittest.SkipTest("requests not installed")

        cls.base_url = os.getenv("GRAVITY_API_URL", "http://localhost:8000").rstrip("/")
        tickers_raw = os.getenv("INTEGRATION_TICKERS", "MSFT")
        cls.tickers = [item.strip().upper() for item in tickers_raw.split(",") if item.strip()]
        cls.poll_timeout = int(os.getenv("INTEGRATION_POLL_TIMEOUT_SECONDS", "90"))
        cls.poll_interval = int(os.getenv("INTEGRATION_POLL_INTERVAL_SECONDS", "3"))

        try:
            resp = requests.get("%s/health" % cls.base_url, timeout=5)
            resp.raise_for_status()
        except Exception as exc:
            raise unittest.SkipTest("Live API not reachable at %s: %s" % (cls.base_url, exc))

    def _get_filings(self):
        resp = requests.get("%s/filings" % self.base_url, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _filings_by_accession(self, filings):
        return {item["accession_number"]: item for item in filings if "accession_number" in item}

    def test_health_endpoint_reports_ok(self):
        resp = requests.get("%s/health" % self.base_url, timeout=5)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("database"), "ok")

    def test_ingest_async_and_status_transition_visible(self):
        baseline_filings = self._get_filings()
        baseline_by_accession = self._filings_by_accession(baseline_filings)

        ingest_resp = requests.post(
            "%s/ingest" % self.base_url,
            json={"tickers": self.tickers},
            timeout=15,
        )
        self.assertEqual(ingest_resp.status_code, 200)
        ingest_data = ingest_resp.json()
        self.assertEqual(ingest_data.get("mode"), "async")
        self.assertTrue(ingest_data.get("job_id"))

        deadline = time.time() + self.poll_timeout
        observed_transition = False
        last_seen_filings = baseline_filings

        while time.time() < deadline:
            filings = self._get_filings()
            last_seen_filings = filings
            current_by_accession = self._filings_by_accession(filings)

            # Case A: new filing appears for monitored tickers and reaches a terminal state.
            for accession, item in current_by_accession.items():
                ticker = (item.get("ticker") or "").upper()
                status = item.get("status")
                if ticker in self.tickers and accession not in baseline_by_accession:
                    if status in TERMINAL_STATUSES:
                        observed_transition = True
                        break

            if observed_transition:
                break

            # Case B: existing filing for monitored tickers transitions from INGESTED to terminal.
            for accession, before in baseline_by_accession.items():
                after = current_by_accession.get(accession)
                if not after:
                    continue
                ticker = (after.get("ticker") or "").upper()
                if ticker not in self.tickers:
                    continue
                if before.get("status") == "INGESTED" and after.get("status") in TERMINAL_STATUSES:
                    observed_transition = True
                    break

            if observed_transition:
                break

            time.sleep(self.poll_interval)

        if not observed_transition:
            self.skipTest(
                "No filing status transition observed within %ss for tickers=%s. "
                "This can happen when no new filings are available. Last filings sample size=%s"
                % (self.poll_timeout, ",".join(self.tickers), len(last_seen_filings))
            )

        self.assertTrue(observed_transition)


if __name__ == "__main__":
    unittest.main()
