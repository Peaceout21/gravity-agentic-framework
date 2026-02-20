"""Unit tests for India market providers."""

import unittest

from core.tools.india_providers import BseProvider, NseProvider


class _Resp(object):
    def __init__(self, status_code=200, json_payload=None, text_payload=""):
        self.status_code = status_code
        self._json_payload = json_payload
        self.text = text_payload

    def json(self):
        return self._json_payload


class _Session(object):
    def __init__(self, responses):
        self.responses = responses
        self.headers = {}

    def get(self, url, timeout=20):  # noqa: ARG002
        return self.responses.get(url, _Resp(status_code=404, json_payload=None, text_payload=""))


class IndiaProvidersTests(unittest.TestCase):
    def test_nse_recent_events_normalizes_to_utc(self):
        api_url = "https://www.nseindia.com/api/corporate-announcements?symbol=INFY"
        session = _Session(
            {
                api_url: _Resp(
                    json_payload=[
                        {
                            "symbol": "INFY",
                            "subject": "Financial Results for quarter ended",
                            "an_dt": "15-Feb-2026 09:20:00",
                            "attchmntFile": "/content/infy_q3_results.pdf",
                            "isin": "INE009A01021",
                            "id": "abc123",
                        }
                    ]
                )
            }
        )
        provider = NseProvider(session=session)
        rows = provider.get_recent_events(["INFY"], per_instrument_limit=5)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.market, "IN_NSE")
        self.assertEqual(row.exchange, "NSE")
        self.assertEqual(row.ticker, "INFY")
        self.assertEqual(row.metadata.get("event_time_utc"), "2026-02-15T03:50:00Z")
        self.assertEqual(row.metadata.get("document_type"), "results")
        self.assertTrue(row.filing_url.startswith("https://nsearchives.nseindia.com/"))
        self.assertTrue(row.accession_number.startswith("nse:INFY:"))

    def test_bse_malformed_payload_returns_empty(self):
        api_url = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?strType=C&strPrevDate=&strScrip=TCS"
        session = _Session({api_url: _Resp(json_payload={"unexpected": "shape"})})
        provider = BseProvider(session=session)
        rows = provider.get_latest_events(["TCS"])
        self.assertEqual(rows, [])

    def test_document_text_is_cleaned(self):
        api_url = "https://www.nseindia.com/api/corporate-announcements?symbol=RELIANCE"
        doc_url = "https://nsearchives.nseindia.com/content/reliance.html"
        session = _Session(
            {
                api_url: _Resp(
                    json_payload=[
                        {
                            "symbol": "RELIANCE",
                            "subject": "Investor presentation",
                            "attchmntFile": "/content/reliance.html",
                            "an_dt": "2026-02-15T08:00:00+05:30",
                            "id": "1",
                        }
                    ]
                ),
                doc_url: _Resp(text_payload="<html><body><h1>Revenue</h1><p>Growth</p></body></html>"),
            }
        )
        provider = NseProvider(session=session)
        rows = provider.get_latest_events(["RELIANCE"])
        text = provider.get_document_text(rows[0])
        self.assertIn("Revenue", text)
        self.assertIn("Growth", text)


if __name__ == "__main__":
    unittest.main()
