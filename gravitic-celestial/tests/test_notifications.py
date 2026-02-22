import unittest

from services.notifications import create_filing_notifications


class DummyPayload(object):
    def __init__(self, ticker, accession_number, filing_url):
        self.ticker = ticker
        self.accession_number = accession_number
        self.filing_url = filing_url


class NotificationsTests(unittest.TestCase):
    def test_create_filing_notifications_for_subscribers(self):
        class StubStateManager(object):
            def __init__(self):
                self.created = []

            def list_watchlist_subscribers(self, org_id, ticker, market="US_SEC", exchange=None):
                _ = market
                _ = exchange
                if org_id != "o1":
                    return []
                return ["u1", "u2"] if ticker == "MSFT" else []

            def create_notification(self, **kwargs):
                self.created.append(kwargs)

        sm = StubStateManager()
        payloads = [DummyPayload("MSFT", "A1", "http://x"), DummyPayload("AAPL", "A2", "http://y")]
        created = create_filing_notifications(sm, payloads, org_id="o1")

        self.assertEqual(created, 2)
        self.assertEqual(len(sm.created), 2)
        self.assertEqual(sm.created[0]["ticker"], "MSFT")


if __name__ == "__main__":
    unittest.main()
