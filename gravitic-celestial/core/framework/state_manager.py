"""SQLite-backed ingestion and processing state."""

import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional


class StateManager(object):
    def __init__(self, db_path="data/state.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS filings (
                    accession_number TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    filing_url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    source TEXT NOT NULL,
                    payload TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlists (
                    org_id TEXT NOT NULL DEFAULT 'default',
                    user_id TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(org_id, user_id, ticker)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    org_id TEXT NOT NULL DEFAULT 'default',
                    user_id TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    accession_number TEXT NOT NULL,
                    notification_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "watchlists", "org_id", "TEXT NOT NULL DEFAULT 'default'")
            self._ensure_column(conn, "notifications", "org_id", "TEXT NOT NULL DEFAULT 'default'")
            conn.commit()

    @staticmethod
    def _ensure_column(conn, table_name, column_name, column_ddl):
        cur = conn.execute("PRAGMA table_info(%s)" % table_name)
        existing = {row[1] for row in cur.fetchall()}
        if column_name not in existing:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table_name, column_name, column_ddl))

    def has_accession(self, accession_number):
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT 1 FROM filings WHERE accession_number = ?",
                (accession_number,),
            )
            return cur.fetchone() is not None

    def upsert_filing(self, accession_number, ticker, filing_url, status):
        now = datetime.utcnow().isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO filings (accession_number, ticker, filing_url, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(accession_number)
                    DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at
                    """,
                    (accession_number, ticker, filing_url, status, now, now),
                )
                conn.commit()

    def mark_ingested(self, accession_number, ticker, filing_url):
        self.upsert_filing(accession_number, ticker, filing_url, "INGESTED")

    def mark_analyzed(self, accession_number, ticker, filing_url):
        self.upsert_filing(accession_number, ticker, filing_url, "ANALYZED")

    def mark_analyzed_not_indexed(self, accession_number, ticker, filing_url):
        self.upsert_filing(accession_number, ticker, filing_url, "ANALYZED_NOT_INDEXED")

    def mark_dead_letter(self, accession_number, ticker, filing_url):
        self.upsert_filing(accession_number, ticker, filing_url, "DEAD_LETTER")

    def log_event(self, topic, source, payload_text=""):
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO events(topic, source, payload, created_at) VALUES (?, ?, ?, ?)",
                (topic, source, payload_text, now),
            )
            conn.commit()

    def list_recent_filings(self, limit=20):
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT accession_number, ticker, filing_url, status, updated_at
                FROM filings
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [
            {
                "accession_number": row[0],
                "ticker": row[1],
                "filing_url": row[2],
                "status": row[3],
                "updated_at": row[4],
            }
            for row in rows
        ]

    def add_watchlist_ticker(self, org_id, user_id, ticker):
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO watchlists(org_id, user_id, ticker, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(org_id, user_id, ticker) DO NOTHING
                """,
                (org_id, user_id, ticker.upper(), now),
            )
            conn.commit()

    def remove_watchlist_ticker(self, org_id, user_id, ticker):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM watchlists WHERE org_id = ? AND user_id = ? AND ticker = ?",
                (org_id, user_id, ticker.upper()),
            )
            conn.commit()

    def list_watchlist(self, org_id, user_id):
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT ticker, created_at
                FROM watchlists
                WHERE org_id = ? AND user_id = ?
                ORDER BY ticker ASC
                """,
                (org_id, user_id),
            )
            rows = cur.fetchall()
        return [{"ticker": row[0], "created_at": row[1]} for row in rows]

    def list_watchlist_subscribers(self, org_id, ticker):
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT user_id FROM watchlists WHERE org_id = ? AND ticker = ?",
                (org_id, ticker.upper()),
            )
            rows = cur.fetchall()
        return [row[0] for row in rows]

    def create_notification(self, org_id, user_id, ticker, accession_number, notification_type, title, body):
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO notifications(
                    org_id, user_id, ticker, accession_number, notification_type, title, body, is_read, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (org_id, user_id, ticker.upper(), accession_number, notification_type, title, body, now),
            )
            conn.commit()

    def list_notifications(self, org_id, user_id, limit=50, unread_only=False, ticker=None, notification_type=None):
        query = """
            SELECT id, org_id, user_id, ticker, accession_number, notification_type, title, body, is_read, created_at
            FROM notifications
            WHERE org_id = ? AND user_id = ?
        """
        params = [org_id, user_id]
        if unread_only:
            query += " AND is_read = 0"
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker.upper())
        if notification_type:
            query += " AND notification_type = ?"
            params.append(notification_type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            cur = conn.execute(query, tuple(params))
            rows = cur.fetchall()
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
                "created_at": row[9],
            }
            for row in rows
        ]

    def mark_notification_read(self, org_id, user_id, notification_id):
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE notifications SET is_read = 1 WHERE id = ? AND org_id = ? AND user_id = ?",
                (notification_id, org_id, user_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def mark_all_notifications_read(self, org_id, user_id, ticker=None, notification_type=None, before=None):
        # type: (str, str, Optional[str], Optional[str], Optional[str]) -> int
        query = "UPDATE notifications SET is_read = 1 WHERE org_id = ? AND user_id = ? AND is_read = 0"
        params = [org_id, user_id]  # type: List[Any]
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker.upper())
        if notification_type:
            query += " AND notification_type = ?"
            params.append(notification_type)
        if before:
            query += " AND created_at <= ?"
            params.append(before)
        with self._connect() as conn:
            cur = conn.execute(query, tuple(params))
            conn.commit()
            return cur.rowcount

    def count_unread_notifications(self, org_id, user_id):
        # type: (str, str) -> int
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE org_id = ? AND user_id = ? AND is_read = 0",
                (org_id, user_id),
            )
            row = cur.fetchone()
            return row[0] if row else 0

    def count_filings_by_status(self):
        # type: () -> Dict[str, int]
        with self._connect() as conn:
            cur = conn.execute("SELECT status, COUNT(*) FROM filings GROUP BY status")
            rows = cur.fetchall()
        return {row[0]: row[1] for row in rows}

    def count_recent_events(self, minutes=60):
        # type: (int) -> Dict[str, int]
        cutoff = datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT topic, COUNT(*) FROM events
                WHERE created_at >= datetime('now', '-%d minutes')
                GROUP BY topic
                """ % minutes
            )
            rows = cur.fetchall()
        return {row[0]: row[1] for row in rows}

    def list_recent_failures(self, limit=20):
        # type: (int) -> List[Dict[str, Any]]
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT accession_number, ticker, filing_url, status, updated_at
                FROM filings
                WHERE status IN ('DEAD_LETTER', 'ANALYZED_NOT_INDEXED')
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [
            {
                "accession_number": row[0],
                "ticker": row[1],
                "filing_url": row[2],
                "status": row[3],
                "updated_at": row[4],
            }
            for row in rows
        ]
