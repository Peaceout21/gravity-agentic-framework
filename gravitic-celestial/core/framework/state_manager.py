"""SQLite-backed ingestion and processing state."""

import json
import re
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Filing-type inference from EDGAR URLs
# ---------------------------------------------------------------------------
# Pass 1: canonical path segments — handles /10-Q/, /10-K/, /8-K/ etc.
_CANONICAL_PATTERN = re.compile(
    r"/(10-[QK](?:/A)?|8-K(?:/A)?|6-K|20-F|S-1|SD)[/\b]",
    re.IGNORECASE,
)

# Pass 2: compact EDGAR tokens found in filenames / URL slugs.
# Maps lowercase token → canonical form type.
_COMPACT_TOKEN_MAP = {
    "10q": "10-Q",
    "10k": "10-K",
    "10ka": "10-K/A",
    "10qa": "10-Q/A",
    "8k": "8-K",
    "8ka": "8-K/A",
    "6k": "6-K",
    "20f": "20-F",
    "s1": "S-1",
    "def14a": "DEF 14A",
    "defa14a": "DEFA14A",
    "sc13d": "SC 13D",
    "sc13g": "SC 13G",
    "sd": "SD",
}

# Build a single pattern from the token map for fallback matching.
_COMPACT_PATTERN = re.compile(
    r"(?:^|[/\-_.])(%s)(?:[/\-_.]|$)" % "|".join(re.escape(k) for k in _COMPACT_TOKEN_MAP),
    re.IGNORECASE,
)


def _infer_filing_type(url):
    # type: (str) -> Optional[str]
    """Try to extract the SEC form type from a URL using two heuristics."""
    if not url:
        return None
    # Pass 1: canonical path segment
    m = _CANONICAL_PATTERN.search(url)
    if m:
        return m.group(1).upper()
    # Pass 2: compact token in filename / slug
    m = _COMPACT_PATTERN.search(url)
    if m:
        token = m.group(1).lower()
        return _COMPACT_TOKEN_MAP.get(token)
    return None


def _backfill_filing_metadata_impl(fetch_rows, update_row):
    # type: (Any, Any) -> Dict[str, Any]
    """Shared backfill logic used by both SQLite and Postgres state managers."""
    rows = fetch_rows()
    total = len(rows)
    updated = 0
    skipped = 0
    samples = []  # type: List[str]

    for accession, url in rows:
        filing_type = _infer_filing_type(url)
        if filing_type is None:
            skipped += 1
            continue
        ok = update_row(accession, filing_type)
        if ok:
            updated += 1
            if len(samples) < 5:
                samples.append(accession)
        else:
            skipped += 1

    return {
        "updated_count": updated,
        "skipped_count": skipped,
        "total_scanned": total,
        "samples": samples,
    }


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
                    filing_type TEXT,
                    item_code TEXT,
                    filing_date TEXT,
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ask_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    org_id TEXT,
                    template_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    category TEXT NOT NULL,
                    question_template TEXT NOT NULL,
                    requires_ticker INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(org_id, template_key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ask_template_filing_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id INTEGER NOT NULL,
                    filing_type TEXT NOT NULL,
                    item_code TEXT NOT NULL DEFAULT '',
                    weight REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    UNIQUE(template_id, filing_type, item_code),
                    FOREIGN KEY(template_id) REFERENCES ask_templates(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ask_template_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    org_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    template_id INTEGER NOT NULL,
                    ticker TEXT,
                    rendered_question TEXT NOT NULL,
                    relevance_label TEXT NOT NULL,
                    coverage_brief TEXT NOT NULL,
                    answer_markdown TEXT NOT NULL,
                    citations_json TEXT NOT NULL,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(template_id) REFERENCES ask_templates(id) ON DELETE CASCADE
                )
                """
            )
            self._ensure_column(conn, "watchlists", "org_id", "TEXT NOT NULL DEFAULT 'default'")
            self._ensure_column(conn, "notifications", "org_id", "TEXT NOT NULL DEFAULT 'default'")
            self._ensure_column(conn, "filings", "filing_type", "TEXT")
            self._ensure_column(conn, "filings", "item_code", "TEXT")
            self._ensure_column(conn, "filings", "filing_date", "TEXT")
            self._seed_default_ask_templates(conn)
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

    def upsert_filing(
        self,
        accession_number,
        ticker,
        filing_url,
        status,
        filing_type=None,
        item_code=None,
        filing_date=None,
    ):
        now = datetime.utcnow().isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO filings (
                        accession_number, ticker, filing_url, status,
                        filing_type, item_code, filing_date, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(accession_number)
                    DO UPDATE SET
                        status=excluded.status,
                        filing_type=COALESCE(excluded.filing_type, filings.filing_type),
                        item_code=COALESCE(excluded.item_code, filings.item_code),
                        filing_date=COALESCE(excluded.filing_date, filings.filing_date),
                        updated_at=excluded.updated_at
                    """,
                    (
                        accession_number,
                        ticker,
                        filing_url,
                        status,
                        filing_type,
                        item_code,
                        filing_date,
                        now,
                        now,
                    ),
                )
                conn.commit()

    def mark_ingested(self, accession_number, ticker, filing_url, filing_type=None, item_code=None, filing_date=None):
        self.upsert_filing(
            accession_number,
            ticker,
            filing_url,
            "INGESTED",
            filing_type=filing_type,
            item_code=item_code,
            filing_date=filing_date,
        )

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
                SELECT accession_number, ticker, filing_url, status, filing_type, item_code, filing_date, updated_at
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
                "filing_type": row[4] or "",
                "item_code": row[5] or "",
                "filing_date": row[6] or "",
                "updated_at": row[7],
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

    def list_recent_analyzed_filings(self, ticker=None, limit=8):
        # type: (Optional[str], int) -> List[Dict[str, Any]]
        query = """
            SELECT accession_number, ticker, filing_url, status, filing_type, item_code, filing_date, updated_at
            FROM filings
            WHERE status = 'ANALYZED'
        """
        params = []  # type: List[Any]
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker.upper())
        query += " ORDER BY COALESCE(filing_date, updated_at) DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            cur = conn.execute(query, tuple(params))
            rows = cur.fetchall()
        return [
            {
                "accession_number": row[0],
                "ticker": row[1],
                "filing_url": row[2],
                "status": row[3],
                "filing_type": row[4] or "",
                "item_code": row[5] or "",
                "filing_date": row[6] or "",
                "updated_at": row[7],
            }
            for row in rows
        ]

    def list_ask_templates(self, org_id, user_id=None):
        # type: (str, Optional[str]) -> List[Dict[str, Any]]
        _ = user_id
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT id, org_id, template_key, title, description, category, question_template,
                       requires_ticker, enabled, sort_order
                FROM ask_templates
                WHERE enabled = 1 AND (org_id = ? OR org_id IS NULL)
                ORDER BY CASE WHEN org_id = ? THEN 0 ELSE 1 END, sort_order ASC, title ASC
                """,
                (org_id, org_id),
            )
            rows = cur.fetchall()
        seen_keys = set()
        templates = []
        for row in rows:
            key = row[2]
            if key in seen_keys:
                continue
            seen_keys.add(key)
            templates.append(
                {
                    "id": row[0],
                    "org_id": row[1],
                    "template_key": key,
                    "title": row[3],
                    "description": row[4],
                    "category": row[5],
                    "question_template": row[6],
                    "requires_ticker": bool(row[7]),
                    "enabled": bool(row[8]),
                    "sort_order": row[9],
                }
            )
        return templates

    def get_ask_template(self, org_id, template_id):
        # type: (str, int) -> Optional[Dict[str, Any]]
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT id, org_id, template_key, title, description, category, question_template,
                       requires_ticker, enabled, sort_order
                FROM ask_templates
                WHERE id = ? AND enabled = 1 AND (org_id = ? OR org_id IS NULL)
                LIMIT 1
                """,
                (template_id, org_id),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "org_id": row[1],
            "template_key": row[2],
            "title": row[3],
            "description": row[4],
            "category": row[5],
            "question_template": row[6],
            "requires_ticker": bool(row[7]),
            "enabled": bool(row[8]),
            "sort_order": row[9],
        }

    def list_ask_template_rules(self, template_id):
        # type: (int) -> List[Dict[str, Any]]
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT filing_type, item_code, weight
                FROM ask_template_filing_rules
                WHERE template_id = ?
                ORDER BY weight DESC, filing_type ASC
                """,
                (template_id,),
            )
            rows = cur.fetchall()
        return [{"filing_type": row[0], "item_code": row[1] or "", "weight": float(row[2])} for row in rows]

    def create_ask_template_run(
        self,
        org_id,
        user_id,
        template_id,
        ticker,
        rendered_question,
        relevance_label,
        coverage_brief,
        answer_markdown,
        citations,
        latency_ms=0,
    ):
        # type: (...) -> int
        now = datetime.utcnow().isoformat()
        citations_json = json.dumps(citations or [], ensure_ascii=True)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO ask_template_runs(
                    org_id, user_id, template_id, ticker, rendered_question, relevance_label,
                    coverage_brief, answer_markdown, citations_json, latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    org_id,
                    user_id,
                    template_id,
                    ticker.upper() if ticker else None,
                    rendered_question,
                    relevance_label,
                    coverage_brief,
                    answer_markdown,
                    citations_json,
                    int(latency_ms),
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_ask_template_runs(self, org_id, user_id, limit=20):
        # type: (str, str, int) -> List[Dict[str, Any]]
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT r.id, r.template_id, t.title, r.ticker, r.rendered_question, r.relevance_label,
                       r.coverage_brief, r.answer_markdown, r.citations_json, r.latency_ms, r.created_at
                FROM ask_template_runs r
                JOIN ask_templates t ON t.id = r.template_id
                WHERE r.org_id = ? AND r.user_id = ?
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                (org_id, user_id, limit),
            )
            rows = cur.fetchall()
        results = []
        for row in rows:
            try:
                citations = json.loads(row[8] or "[]")
            except Exception:
                citations = []
            results.append(
                {
                    "id": row[0],
                    "template_id": row[1],
                    "template_title": row[2],
                    "ticker": row[3] or "",
                    "rendered_question": row[4],
                    "relevance_label": row[5],
                    "coverage_brief": row[6],
                    "answer_markdown": row[7],
                    "citations": citations,
                    "latency_ms": row[9],
                    "created_at": row[10],
                }
            )
        return results

    def count_filings_for_ticker(self, ticker):
        # type: (str) -> int
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM filings WHERE ticker = ?",
                (ticker.upper(),),
            )
            row = cur.fetchone()
            return row[0] if row else 0

    def backfill_filing_metadata(self):
        # type: () -> Dict[str, Any]
        """Populate filing_type for rows where it is NULL/empty.

        Uses two heuristics in order:
        1. Canonical URL path segments (``/10-Q/``, ``/8-K/``, etc.)
        2. Compact EDGAR tokens often found in filenames (``def14a``, ``sc13d``, ``20f``, etc.)

        Returns a dict with ``updated_count``, ``skipped_count``, ``total_scanned``,
        and ``samples`` (up to 5 updated accession numbers).
        """
        result = _backfill_filing_metadata_impl(
            fetch_rows=lambda: self._fetch_empty_metadata_rows(),
            update_row=lambda acc, ft: self._update_filing_type(acc, ft),
        )
        return result

    def _fetch_empty_metadata_rows(self):
        # type: () -> list
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT accession_number, filing_url FROM filings WHERE filing_type IS NULL OR filing_type = ''"
            )
            return cur.fetchall()

    def _update_filing_type(self, accession, filing_type):
        # type: (str, str) -> bool
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "UPDATE filings SET filing_type = ? WHERE accession_number = ? AND (filing_type IS NULL OR filing_type = '')",
                    (filing_type, accession),
                )
                conn.commit()
                return cur.rowcount > 0

    def _seed_default_ask_templates(self, conn):
        now = datetime.utcnow().isoformat()
        defaults = [
            {
                "key": "qoq_changes",
                "title": "Quarter-over-quarter changes",
                "description": "Summarize what changed versus the previous quarter.",
                "category": "overview",
                "question_template": "What changed versus the previous quarter for {ticker}?",
                "requires_ticker": 1,
                "sort_order": 10,
                "rules": [("10-Q", None, 1.0), ("10-K", None, 0.9), ("8-K", "2.02", 0.6)],
            },
            {
                "key": "kpi_surprises",
                "title": "Top KPI surprises",
                "description": "Highlight top KPI surprises from the latest filing.",
                "category": "kpi",
                "question_template": "What are the top KPI surprises in the latest filing for {ticker}?",
                "requires_ticker": 1,
                "sort_order": 20,
                "rules": [("10-Q", None, 1.0), ("10-K", None, 0.9), ("8-K", "2.02", 0.7)],
            },
            {
                "key": "guidance_shift",
                "title": "Guidance shifts",
                "description": "Find changes in management guidance and implications.",
                "category": "guidance",
                "question_template": "What guidance changes were disclosed for {ticker}, and what do they imply?",
                "requires_ticker": 1,
                "sort_order": 30,
                "rules": [("10-Q", None, 0.9), ("10-K", None, 0.8), ("8-K", "2.02", 1.0)],
            },
            {
                "key": "risk_flags",
                "title": "Key risk flags",
                "description": "Surface notable risks from latest disclosures.",
                "category": "risk",
                "question_template": "What key risks were flagged in the latest filing for {ticker}?",
                "requires_ticker": 1,
                "sort_order": 40,
                "rules": [("10-K", None, 1.0), ("10-Q", None, 0.8), ("8-K", None, 0.4)],
            },
        ]
        for template in defaults:
            conn.execute(
                """
                INSERT OR IGNORE INTO ask_templates(
                    org_id, template_key, title, description, category, question_template,
                    requires_ticker, enabled, sort_order, created_at, updated_at
                ) VALUES (NULL, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    template["key"],
                    template["title"],
                    template["description"],
                    template["category"],
                    template["question_template"],
                    template["requires_ticker"],
                    template["sort_order"],
                    now,
                    now,
                ),
            )
            cur = conn.execute("SELECT id FROM ask_templates WHERE org_id IS NULL AND template_key = ?", (template["key"],))
            row = cur.fetchone()
            if not row:
                continue
            template_id = int(row[0])
            for filing_type, item_code, weight in template["rules"]:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO ask_template_filing_rules(template_id, filing_type, item_code, weight, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (template_id, filing_type, item_code or "", weight, now),
                )
