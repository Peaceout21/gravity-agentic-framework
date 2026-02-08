"""HTTP client for the gravity-api FastAPI service."""

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class GravityApiClient(object):
    """Wraps the four FastAPI endpoints for use by Streamlit (or any client)."""

    def __init__(self, base_url, org_id="default", user_id="default", api_key=None):
        # type: (str, str, str, Optional[str]) -> None
        self.base_url = base_url.rstrip("/")
        self.org_id = org_id
        self.user_id = user_id
        self.api_key = api_key
        self._session = requests.Session()

    def _auth_headers(self):
        # type: () -> Dict[str, str]
        headers = {
            "X-Org-Id": self.org_id,
            "X-User-Id": self.user_id,
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    def health(self):
        # type: () -> Dict[str, str]
        resp = self._session.get("%s/health" % self.base_url, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Filings
    # ------------------------------------------------------------------
    def list_filings(self, limit=25):
        # type: (int) -> List[Dict[str, Any]]
        resp = self._session.get(
            "%s/filings" % self.base_url,
            params={"limit": limit},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    def ingest(self, tickers):
        # type: (List[str]) -> Dict[str, Any]
        resp = self._session.post(
            "%s/ingest" % self.base_url,
            json={"tickers": tickers},
            headers=self._auth_headers(),
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def backfill(self, tickers, per_ticker_limit=8, include_existing=False, notify=False):
        # type: (List[str], int, bool, bool) -> Dict[str, Any]
        resp = self._session.post(
            "%s/backfill" % self.base_url,
            json={
                "tickers": tickers,
                "per_ticker_limit": per_ticker_limit,
                "include_existing": include_existing,
                "notify": notify,
            },
            headers=self._auth_headers(),
            timeout=600,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Question answering
    # ------------------------------------------------------------------
    def query(self, question, ticker=None):
        # type: (str, Optional[str]) -> Dict[str, Any]
        body = {"question": question}  # type: Dict[str, Any]
        if ticker:
            body["ticker"] = ticker
        resp = self._session.post(
            "%s/query" % self.base_url,
            json=body,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def list_ask_templates(self):
        # type: () -> List[Dict[str, Any]]
        resp = self._session.get(
            "%s/ask/templates" % self.base_url,
            headers=self._auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def run_ask_template(self, template_id, ticker=None, params=None):
        # type: (int, Optional[str], Optional[Dict[str, Any]]) -> Dict[str, Any]
        body = {"template_id": int(template_id)}
        if ticker:
            body["ticker"] = ticker.upper()
        if params:
            body["params"] = params
        resp = self._session.post(
            "%s/ask/template-run" % self.base_url,
            json=body,
            headers=self._auth_headers(),
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def list_template_runs(self, limit=20):
        # type: (int) -> List[Dict[str, Any]]
        resp = self._session.get(
            "%s/ask/template-runs" % self.base_url,
            params={"limit": limit},
            headers=self._auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Watchlist
    # ------------------------------------------------------------------
    def list_watchlist(self, user_id="default"):
        _ = user_id  # retained for compatibility; auth header controls user context
        resp = self._session.get(
            "%s/watchlist" % self.base_url,
            headers=self._auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def add_watchlist(self, tickers, user_id="default"):
        _ = user_id
        resp = self._session.post(
            "%s/watchlist" % self.base_url,
            json={"tickers": tickers},
            headers=self._auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def remove_watchlist(self, tickers, user_id="default"):
        _ = user_id
        resp = self._session.request(
            "DELETE",
            "%s/watchlist" % self.base_url,
            json={"tickers": tickers},
            headers=self._auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    def list_notifications(self, user_id="default", limit=50, unread_only=False, ticker=None, notification_type=None):
        _ = user_id
        params = {"limit": limit, "unread_only": unread_only}
        if ticker:
            params["ticker"] = ticker.upper()
        if notification_type:
            params["notification_type"] = notification_type
        resp = self._session.get(
            "%s/notifications" % self.base_url,
            params=params,
            headers=self._auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def mark_notification_read(self, notification_id, user_id="default"):
        _ = user_id
        resp = self._session.post(
            "%s/notifications/%s/read" % (self.base_url, notification_id),
            json={},
            headers=self._auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def read_all_notifications(self, ticker=None, notification_type=None, before=None):
        # type: (Optional[str], Optional[str], Optional[str]) -> Dict[str, Any]
        body = {}  # type: Dict[str, Any]
        if ticker:
            body["ticker"] = ticker
        if notification_type:
            body["notification_type"] = notification_type
        if before:
            body["before"] = before
        resp = self._session.post(
            "%s/notifications/read-all" % self.base_url,
            json=body,
            headers=self._auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def count_unread_notifications(self):
        # type: () -> int
        resp = self._session.get(
            "%s/notifications/count" % self.base_url,
            headers=self._auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("unread", 0)

    def backfill_filing_metadata(self):
        # type: () -> Dict[str, Any]
        resp = self._session.post(
            "%s/filings/backfill-metadata" % self.base_url,
            json={},
            headers=self._auth_headers(),
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def count_filings_for_ticker(self, ticker):
        # type: (str) -> int
        resp = self._session.get(
            "%s/filings/ticker-count" % self.base_url,
            params={"ticker": ticker.strip().upper()},
            headers=self._auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("count", 0)

    # ------------------------------------------------------------------
    # Ops
    # ------------------------------------------------------------------
    def ops_health(self):
        # type: () -> Dict[str, Any]
        resp = self._session.get(
            "%s/ops/health" % self.base_url,
            headers=self._auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def ops_metrics(self, window_minutes=60):
        # type: (int) -> Dict[str, Any]
        resp = self._session.get(
            "%s/ops/metrics" % self.base_url,
            params={"window_minutes": window_minutes},
            headers=self._auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
