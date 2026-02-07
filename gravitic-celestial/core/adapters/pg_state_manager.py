"""Postgres-backed state manager (drop-in replacement for StateManager)."""

import logging
import threading
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class PostgresStateManager(object):
    """Same public interface as core.framework.state_manager.StateManager."""

    def __init__(self, dsn):
        # type: (str) -> None
        import psycopg2
        import psycopg2.pool

        self._dsn = dsn
        self._pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=5, dsn=dsn)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Connection helper
    # ------------------------------------------------------------------
    def _conn(self):
        return self._pool.getconn()

    def _put(self, conn):
        self._pool.putconn(conn)

    # ------------------------------------------------------------------
    # Filing CRUD
    # ------------------------------------------------------------------
    def has_accession(self, accession_number):
        # type: (str) -> bool
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM filings WHERE accession_number = %s",
                    (accession_number,),
                )
                return cur.fetchone() is not None
        finally:
            self._put(conn)

    def upsert_filing(self, accession_number, ticker, filing_url, status):
        # type: (str, str, str, str) -> None
        now = datetime.utcnow()
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO filings (accession_number, ticker, filing_url, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (accession_number)
                    DO UPDATE SET status = EXCLUDED.status, updated_at = EXCLUDED.updated_at
                    """,
                    (accession_number, ticker, filing_url, status, now, now),
                )
            conn.commit()
        finally:
            self._put(conn)

    def mark_ingested(self, accession_number, ticker, filing_url):
        self.upsert_filing(accession_number, ticker, filing_url, "INGESTED")

    def mark_analyzed(self, accession_number, ticker, filing_url):
        self.upsert_filing(accession_number, ticker, filing_url, "ANALYZED")

    def mark_analyzed_not_indexed(self, accession_number, ticker, filing_url):
        self.upsert_filing(accession_number, ticker, filing_url, "ANALYZED_NOT_INDEXED")

    def mark_dead_letter(self, accession_number, ticker, filing_url):
        self.upsert_filing(accession_number, ticker, filing_url, "DEAD_LETTER")

    # ------------------------------------------------------------------
    # Event log
    # ------------------------------------------------------------------
    def log_event(self, topic, source, payload_text=""):
        # type: (str, str, str) -> None
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO events (topic, source, payload) VALUES (%s, %s, %s)",
                    (topic, source, payload_text),
                )
            conn.commit()
        finally:
            self._put(conn)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def list_recent_filings(self, limit=20):
        # type: (int) -> List[Dict[str, Any]]
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT accession_number, ticker, filing_url, status, updated_at
                    FROM filings
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
        finally:
            self._put(conn)

        return [
            {
                "accession_number": row[0],
                "ticker": row[1],
                "filing_url": row[2],
                "status": row[3],
                "updated_at": row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
            }
            for row in rows
        ]

    def add_watchlist_ticker(self, org_id, user_id, ticker):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO watchlists(org_id, user_id, ticker)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (org_id, user_id, ticker) DO NOTHING
                    """,
                    (org_id, user_id, ticker.upper()),
                )
            conn.commit()
        finally:
            self._put(conn)

    def remove_watchlist_ticker(self, org_id, user_id, ticker):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM watchlists WHERE org_id = %s AND user_id = %s AND ticker = %s",
                    (org_id, user_id, ticker.upper()),
                )
            conn.commit()
        finally:
            self._put(conn)

    def list_watchlist(self, org_id, user_id):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ticker, created_at
                    FROM watchlists
                    WHERE org_id = %s AND user_id = %s
                    ORDER BY ticker ASC
                    """,
                    (org_id, user_id),
                )
                rows = cur.fetchall()
        finally:
            self._put(conn)
        return [
            {"ticker": row[0], "created_at": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1])}
            for row in rows
        ]

    def list_watchlist_subscribers(self, org_id, ticker):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM watchlists WHERE org_id = %s AND ticker = %s", (org_id, ticker.upper()))
                rows = cur.fetchall()
        finally:
            self._put(conn)
        return [row[0] for row in rows]

    def create_notification(self, org_id, user_id, ticker, accession_number, notification_type, title, body):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO notifications(
                        org_id, user_id, ticker, accession_number, notification_type, title, body, is_read
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
                    """,
                    (org_id, user_id, ticker.upper(), accession_number, notification_type, title, body),
                )
            conn.commit()
        finally:
            self._put(conn)

    def list_notifications(self, org_id, user_id, limit=50, unread_only=False, ticker=None, notification_type=None):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                query = """
                    SELECT id, org_id, user_id, ticker, accession_number, notification_type, title, body, is_read, created_at
                    FROM notifications
                    WHERE org_id = %s AND user_id = %s
                """
                params = [org_id, user_id]
                if unread_only:
                    query += " AND is_read = FALSE"
                if ticker:
                    query += " AND ticker = %s"
                    params.append(ticker.upper())
                if notification_type:
                    query += " AND notification_type = %s"
                    params.append(notification_type)
                query += " ORDER BY created_at DESC LIMIT %s"
                params.append(limit)
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        finally:
            self._put(conn)
        return [
            {
                "id": row[0],
                "org_id": row[1],
                "user_id": row[2],
                "ticker": row[3],
                "accession_number": row[4],
                "notification_type": row[5],
                "title": row[6],
                "body": row[7],
                "is_read": bool(row[8]),
                "created_at": row[9].isoformat() if hasattr(row[9], "isoformat") else str(row[9]),
            }
            for row in rows
        ]

    def mark_notification_read(self, org_id, user_id, notification_id):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE notifications SET is_read = TRUE WHERE id = %s AND org_id = %s AND user_id = %s",
                    (notification_id, org_id, user_id),
                )
                updated = cur.rowcount > 0
            conn.commit()
            return updated
        finally:
            self._put(conn)

    def mark_all_notifications_read(self, org_id, user_id, ticker=None, notification_type=None, before=None):
        conn = self._conn()
        try:
            query = "UPDATE notifications SET is_read = TRUE WHERE org_id = %s AND user_id = %s AND is_read = FALSE"
            params = [org_id, user_id]
            if ticker:
                query += " AND ticker = %s"
                params.append(ticker.upper())
            if notification_type:
                query += " AND notification_type = %s"
                params.append(notification_type)
            if before:
                query += " AND created_at <= %s"
                params.append(before)
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                count = cur.rowcount
            conn.commit()
            return count
        finally:
            self._put(conn)

    def count_unread_notifications(self, org_id, user_id):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM notifications WHERE org_id = %s AND user_id = %s AND is_read = FALSE",
                    (org_id, user_id),
                )
                row = cur.fetchone()
                return row[0] if row else 0
        finally:
            self._put(conn)

    def count_filings_by_status(self):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT status, COUNT(*) FROM filings GROUP BY status")
                rows = cur.fetchall()
        finally:
            self._put(conn)
        return {row[0]: row[1] for row in rows}

    def count_recent_events(self, minutes=60):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT topic, COUNT(*) FROM events
                    WHERE created_at >= now() - interval '%s minutes'
                    GROUP BY topic
                    """,
                    (minutes,),
                )
                rows = cur.fetchall()
        finally:
            self._put(conn)
        return {row[0]: row[1] for row in rows}

    def list_recent_failures(self, limit=20):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT accession_number, ticker, filing_url, status, updated_at
                    FROM filings
                    WHERE status IN ('DEAD_LETTER', 'ANALYZED_NOT_INDEXED')
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
        finally:
            self._put(conn)
        return [
            {
                "accession_number": row[0],
                "ticker": row[1],
                "filing_url": row[2],
                "status": row[3],
                "updated_at": row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
            }
            for row in rows
        ]
