"""Postgres-backed state manager (drop-in replacement for StateManager)."""

import json
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

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
        self._seed_default_ask_templates()

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

    def upsert_filing(
        self,
        accession_number,
        ticker,
        filing_url,
        status,
        filing_type=None,
        item_code=None,
        filing_date=None,
        market="US_SEC",
        exchange="",
        issuer_id="",
        source="",
        source_event_id="",
        document_type="",
        currency="",
        dead_letter_reason=None,
        last_error=None,
    ):
        # type: (str, str, str, str, Optional[str], Optional[str], Optional[str], str, str, str, str, str, str, str) -> None
        now = datetime.utcnow()
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO filings (
                        accession_number, ticker, filing_url, status,
                        dead_letter_reason, last_error,
                        market, exchange, issuer_id, source, source_event_id, document_type, currency,
                        filing_type, item_code, filing_date, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (accession_number)
                    DO UPDATE SET
                        status = EXCLUDED.status,
                        dead_letter_reason = EXCLUDED.dead_letter_reason,
                        last_error = EXCLUDED.last_error,
                        market = COALESCE(EXCLUDED.market, filings.market),
                        exchange = COALESCE(EXCLUDED.exchange, filings.exchange),
                        issuer_id = COALESCE(EXCLUDED.issuer_id, filings.issuer_id),
                        source = COALESCE(EXCLUDED.source, filings.source),
                        source_event_id = COALESCE(EXCLUDED.source_event_id, filings.source_event_id),
                        document_type = COALESCE(EXCLUDED.document_type, filings.document_type),
                        currency = COALESCE(EXCLUDED.currency, filings.currency),
                        filing_type = COALESCE(EXCLUDED.filing_type, filings.filing_type),
                        item_code = COALESCE(EXCLUDED.item_code, filings.item_code),
                        filing_date = COALESCE(EXCLUDED.filing_date, filings.filing_date),
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        accession_number,
                        ticker,
                        filing_url,
                        status,
                        dead_letter_reason,
                        last_error,
                        (market or "US_SEC"),
                        exchange or "",
                        issuer_id or "",
                        source or "",
                        source_event_id or "",
                        document_type or "",
                        currency or "",
                        filing_type,
                        item_code,
                        filing_date,
                        now,
                        now,
                    ),
                )
            conn.commit()
        finally:
            self._put(conn)

    def mark_ingested(
        self,
        accession_number,
        ticker,
        filing_url,
        filing_type=None,
        item_code=None,
        filing_date=None,
        market="US_SEC",
        exchange="",
        issuer_id="",
        source="",
        source_event_id="",
        document_type="",
        currency="",
    ):
        self.upsert_filing(
            accession_number,
            ticker,
            filing_url,
            "INGESTED",
            filing_type=filing_type,
            item_code=item_code,
            filing_date=filing_date,
            market=market,
            exchange=exchange,
            issuer_id=issuer_id,
            source=source,
            source_event_id=source_event_id,
            document_type=document_type,
            currency=currency,
        )

    def mark_analyzed(self, accession_number, ticker, filing_url):
        self.upsert_filing(accession_number, ticker, filing_url, "ANALYZED", dead_letter_reason=None, last_error=None)

    def mark_analyzed_not_indexed(self, accession_number, ticker, filing_url):
        self.upsert_filing(
            accession_number, ticker, filing_url, "ANALYZED_NOT_INDEXED", dead_letter_reason=None, last_error=None
        )

    def mark_dead_letter(self, accession_number, ticker, filing_url, reason=None, error=None):
        self.upsert_filing(
            accession_number,
            ticker,
            filing_url,
            "DEAD_LETTER",
            dead_letter_reason=(reason or ""),
            last_error=(error or ""),
        )

    def get_filing(self, accession_number):
        # type: (str) -> Optional[Dict[str, Any]]
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT accession_number, ticker, filing_url, status, dead_letter_reason, last_error, replay_count, last_replay_at,
                           market, exchange, issuer_id, source, source_event_id, document_type, currency,
                           filing_type, item_code, filing_date, created_at, updated_at
                    FROM filings
                    WHERE accession_number = %s
                    """,
                    (accession_number,),
                )
                row = cur.fetchone()
        finally:
            self._put(conn)
        if not row:
            return None
        return {
            "accession_number": row[0],
            "ticker": row[1],
            "filing_url": row[2],
            "status": row[3],
            "dead_letter_reason": row[4] or "",
            "last_error": row[5] or "",
            "replay_count": int(row[6] or 0),
            "last_replay_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7] or ""),
            "market": row[8] or "US_SEC",
            "exchange": row[9] or "",
            "issuer_id": row[10] or "",
            "source": row[11] or "",
            "source_event_id": row[12] or "",
            "document_type": row[13] or "",
            "currency": row[14] or "",
            "filing_type": row[15] or "",
            "item_code": row[16] or "",
            "filing_date": row[17].isoformat() if hasattr(row[17], "isoformat") else str(row[17] or ""),
            "created_at": row[18].isoformat() if hasattr(row[18], "isoformat") else str(row[18] or ""),
            "updated_at": row[19].isoformat() if hasattr(row[19], "isoformat") else str(row[19] or ""),
        }

    def mark_replay_attempt(self, accession_number):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE filings
                    SET replay_count = COALESCE(replay_count, 0) + 1,
                        last_replay_at = now()
                    WHERE accession_number = %s
                    """,
                    (accession_number,),
                )
            conn.commit()
        finally:
            self._put(conn)

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
                    SELECT accession_number, ticker, filing_url, status, dead_letter_reason, last_error, replay_count, last_replay_at,
                           market, exchange, issuer_id, source, source_event_id,
                           document_type, currency, filing_type, item_code, filing_date, updated_at
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
                "dead_letter_reason": row[4] or "",
                "last_error": row[5] or "",
                "replay_count": int(row[6] or 0),
                "last_replay_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7] or ""),
                "market": row[8] or "US_SEC",
                "exchange": row[9] or "",
                "issuer_id": row[10] or "",
                "source": row[11] or "",
                "source_event_id": row[12] or "",
                "document_type": row[13] or "",
                "currency": row[14] or "",
                "filing_type": row[15] or "",
                "item_code": row[16] or "",
                "filing_date": row[17].isoformat() if hasattr(row[17], "isoformat") else str(row[17] or ""),
                "updated_at": row[18].isoformat() if hasattr(row[18], "isoformat") else str(row[18]),
            }
            for row in rows
        ]

    def add_watchlist_ticker(self, org_id, user_id, ticker, market="US_SEC", exchange=""):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO watchlists(org_id, user_id, ticker, market, exchange)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (org_id, user_id, ticker) DO UPDATE SET
                        market = EXCLUDED.market,
                        exchange = EXCLUDED.exchange
                    """,
                    (org_id, user_id, ticker.upper(), (market or "US_SEC").upper(), (exchange or "").upper()),
                )
            conn.commit()
        finally:
            self._put(conn)

    def remove_watchlist_ticker(self, org_id, user_id, ticker, market=None, exchange=None):
        conn = self._conn()
        try:
            query = "DELETE FROM watchlists WHERE org_id = %s AND user_id = %s AND ticker = %s"
            params = [org_id, user_id, ticker.upper()]
            if market:
                query += " AND market = %s"
                params.append(market.upper())
            if exchange:
                query += " AND exchange = %s"
                params.append(exchange.upper())
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
            conn.commit()
        finally:
            self._put(conn)

    def list_watchlist(self, org_id, user_id, market=None):
        conn = self._conn()
        try:
            query = """
                    SELECT ticker, market, exchange, created_at
                    FROM watchlists
                    WHERE org_id = %s AND user_id = %s
                """
            params = [org_id, user_id]
            if market:
                query += " AND market = %s"
                params.append(market.upper())
            query += " ORDER BY ticker ASC"
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        finally:
            self._put(conn)
        return [
            {
                "ticker": row[0],
                "market": row[1] or "US_SEC",
                "exchange": row[2] or "",
                "created_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
            }
            for row in rows
        ]

    def list_watchlist_subscribers(self, org_id, ticker, market="US_SEC", exchange=None):
        conn = self._conn()
        try:
            query = "SELECT user_id FROM watchlists WHERE org_id = %s AND ticker = %s AND market = %s"
            params = [org_id, ticker.upper(), (market or "US_SEC").upper()]
            if exchange:
                query += " AND exchange = %s"
                params.append(exchange.upper())
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        finally:
            self._put(conn)
        return [row[0] for row in rows]

    def create_notification(
        self,
        org_id,
        user_id,
        ticker,
        accession_number,
        notification_type,
        title,
        body,
        market="US_SEC",
        exchange="",
    ):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO notifications(
                        org_id, user_id, ticker, market, exchange, accession_number, notification_type, title, body, is_read
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
                    """,
                    (
                        org_id,
                        user_id,
                        ticker.upper(),
                        (market or "US_SEC").upper(),
                        (exchange or "").upper(),
                        accession_number,
                        notification_type,
                        title,
                        body,
                    ),
                )
            conn.commit()
        finally:
            self._put(conn)

    def list_notifications(self, org_id, user_id, limit=50, unread_only=False, ticker=None, notification_type=None):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                query = """
                    SELECT id, org_id, user_id, ticker, market, exchange, accession_number, notification_type, title, body, is_read, created_at
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
                "market": row[4] or "US_SEC",
                "exchange": row[5] or "",
                "accession_number": row[6],
                "notification_type": row[7],
                "title": row[8],
                "body": row[9],
                "is_read": bool(row[10]),
                "created_at": row[11].isoformat() if hasattr(row[11], "isoformat") else str(row[11]),
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
                    SELECT accession_number, ticker, filing_url, status, updated_at,
                           dead_letter_reason, last_error, replay_count, last_replay_at
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
                "dead_letter_reason": row[5] or "",
                "last_error": row[6] or "",
                "replay_count": int(row[7] or 0),
                "last_replay_at": row[8].isoformat() if hasattr(row[8], "isoformat") else str(row[8] or ""),
            }
            for row in rows
        ]

    def list_recent_analyzed_filings(self, ticker=None, limit=8):
        # type: (Optional[str], int) -> List[Dict[str, Any]]
        conn = self._conn()
        try:
            query = """
                SELECT accession_number, ticker, filing_url, status, market, exchange, issuer_id, source, source_event_id,
                       document_type, currency, filing_type, item_code, filing_date, updated_at
                FROM filings
                WHERE status = 'ANALYZED'
            """
            params = []  # type: List[Any]
            if ticker:
                query += " AND ticker = %s"
                params.append(ticker.upper())
            query += " ORDER BY COALESCE(filing_date, updated_at::date) DESC, updated_at DESC LIMIT %s"
            params.append(limit)
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        finally:
            self._put(conn)
        return [
            {
                "accession_number": row[0],
                "ticker": row[1],
                "filing_url": row[2],
                "status": row[3],
                "market": row[4] or "US_SEC",
                "exchange": row[5] or "",
                "issuer_id": row[6] or "",
                "source": row[7] or "",
                "source_event_id": row[8] or "",
                "document_type": row[9] or "",
                "currency": row[10] or "",
                "filing_type": row[11] or "",
                "item_code": row[12] or "",
                "filing_date": row[13].isoformat() if hasattr(row[13], "isoformat") else str(row[13] or ""),
                "updated_at": row[14].isoformat() if hasattr(row[14], "isoformat") else str(row[14]),
            }
            for row in rows
        ]

    def list_ask_templates(self, org_id, user_id=None):
        # type: (str, Optional[str]) -> List[Dict[str, Any]]
        _ = user_id
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, org_id, template_key, title, description, category, question_template,
                           requires_ticker, enabled, sort_order
                    FROM ask_templates
                    WHERE enabled = TRUE AND (org_id = %s OR org_id IS NULL)
                    ORDER BY CASE WHEN org_id = %s THEN 0 ELSE 1 END, sort_order ASC, title ASC
                    """,
                    (org_id, org_id),
                )
                rows = cur.fetchall()
        finally:
            self._put(conn)
        seen_keys = set()
        templates = []
        for row in rows:
            if row[2] in seen_keys:
                continue
            seen_keys.add(row[2])
            templates.append(
                {
                    "id": row[0],
                    "org_id": row[1],
                    "template_key": row[2],
                    "title": row[3],
                    "description": row[4],
                    "category": row[5],
                    "question_template": row[6],
                    "requires_ticker": bool(row[7]),
                    "enabled": bool(row[8]),
                    "sort_order": int(row[9]),
                }
            )
        return templates

    def get_ask_template(self, org_id, template_id):
        # type: (str, int) -> Optional[Dict[str, Any]]
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, org_id, template_key, title, description, category, question_template,
                           requires_ticker, enabled, sort_order
                    FROM ask_templates
                    WHERE id = %s AND enabled = TRUE AND (org_id = %s OR org_id IS NULL)
                    LIMIT 1
                    """,
                    (template_id, org_id),
                )
                row = cur.fetchone()
        finally:
            self._put(conn)
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
            "sort_order": int(row[9]),
        }

    def list_ask_template_rules(self, template_id):
        # type: (int) -> List[Dict[str, Any]]
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT filing_type, item_code, weight
                    FROM ask_template_filing_rules
                    WHERE template_id = %s
                    ORDER BY weight DESC, filing_type ASC
                    """,
                    (template_id,),
                )
                rows = cur.fetchall()
        finally:
            self._put(conn)
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
        confidence=0.0,
        derivation_trace=None,
        latency_ms=0,
    ):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ask_template_runs(
                        org_id, user_id, template_id, ticker, rendered_question, relevance_label,
                        coverage_brief, answer_markdown, citations_json, confidence, derivation_trace_json, latency_ms
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s)
                    RETURNING id
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
                        json.dumps(citations or [], ensure_ascii=True),
                        float(confidence or 0.0),
                        json.dumps(derivation_trace or [], ensure_ascii=True),
                        int(latency_ms),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
            return int(row[0]) if row else 0
        finally:
            self._put(conn)

    def list_ask_template_runs(self, org_id, user_id, limit=20):
        # type: (str, str, int) -> List[Dict[str, Any]]
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT r.id, r.template_id, t.title, r.ticker, r.rendered_question, r.relevance_label,
                           r.coverage_brief, r.answer_markdown, r.citations_json::text, r.confidence, r.derivation_trace_json::text,
                           r.latency_ms, r.created_at
                    FROM ask_template_runs r
                    JOIN ask_templates t ON t.id = r.template_id
                    WHERE r.org_id = %s AND r.user_id = %s
                    ORDER BY r.created_at DESC
                    LIMIT %s
                    """,
                    (org_id, user_id, limit),
                )
                rows = cur.fetchall()
        finally:
            self._put(conn)
        results = []
        for row in rows:
            try:
                citations = json.loads(row[8] or "[]")
            except Exception:
                citations = []
            try:
                derivation_trace = json.loads(row[10] or "[]")
            except Exception:
                derivation_trace = []
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
                    "confidence": float(row[9] or 0.0),
                    "derivation_trace": derivation_trace,
                    "latency_ms": row[11],
                    "created_at": row[12].isoformat() if hasattr(row[12], "isoformat") else str(row[12]),
                }
            )
        return results

    def count_filings_for_ticker(self, ticker):
        # type: (str) -> int
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM filings WHERE ticker = %s",
                    (ticker.upper(),),
                )
                row = cur.fetchone()
                return row[0] if row else 0
        finally:
            self._put(conn)

    def backfill_filing_metadata(self):
        # type: () -> Dict[str, Any]
        """Populate filing_type for rows where it is NULL/empty."""
        from core.framework.state_manager import _backfill_filing_metadata_impl

        return _backfill_filing_metadata_impl(
            fetch_rows=lambda: self._fetch_empty_metadata_rows(),
            update_row=lambda acc, ft: self._update_filing_type(acc, ft),
        )

    def _fetch_empty_metadata_rows(self):
        # type: () -> list
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT accession_number, filing_url FROM filings WHERE filing_type IS NULL OR filing_type = ''"
                )
                return cur.fetchall()
        finally:
            self._put(conn)

    def _update_filing_type(self, accession, filing_type):
        # type: (str, str) -> bool
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE filings SET filing_type = %s WHERE accession_number = %s AND (filing_type IS NULL OR filing_type = '')",
                    (filing_type, accession),
                )
                ok = cur.rowcount > 0
            conn.commit()
            return ok
        finally:
            self._put(conn)

    def _seed_default_ask_templates(self):
        defaults = [
            {
                "key": "qoq_changes",
                "title": "Quarter-over-quarter changes",
                "description": "Summarize what changed versus the previous quarter.",
                "category": "overview",
                "question_template": "What changed versus the previous quarter for {ticker}?",
                "requires_ticker": True,
                "sort_order": 10,
                "rules": [("10-Q", None, 1.0), ("10-K", None, 0.9), ("8-K", "2.02", 0.6)],
            },
            {
                "key": "kpi_surprises",
                "title": "Top KPI surprises",
                "description": "Highlight top KPI surprises from the latest filing.",
                "category": "kpi",
                "question_template": "What are the top KPI surprises in the latest filing for {ticker}?",
                "requires_ticker": True,
                "sort_order": 20,
                "rules": [("10-Q", None, 1.0), ("10-K", None, 0.9), ("8-K", "2.02", 0.7)],
            },
            {
                "key": "guidance_shift",
                "title": "Guidance shifts",
                "description": "Find changes in management guidance and implications.",
                "category": "guidance",
                "question_template": "What guidance changes were disclosed for {ticker}, and what do they imply?",
                "requires_ticker": True,
                "sort_order": 30,
                "rules": [("10-Q", None, 0.9), ("10-K", None, 0.8), ("8-K", "2.02", 1.0)],
            },
            {
                "key": "risk_flags",
                "title": "Key risk flags",
                "description": "Surface notable risks from latest disclosures.",
                "category": "risk",
                "question_template": "What key risks were flagged in the latest filing for {ticker}?",
                "requires_ticker": True,
                "sort_order": 40,
                "rules": [("10-K", None, 1.0), ("10-Q", None, 0.8), ("8-K", None, 0.4)],
            },
        ]
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                for template in defaults:
                    cur.execute(
                        """
                        INSERT INTO ask_templates(
                            org_id, template_key, title, description, category, question_template,
                            requires_ticker, enabled, sort_order
                        ) VALUES (NULL, %s, %s, %s, %s, %s, %s, TRUE, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            template["key"],
                            template["title"],
                            template["description"],
                            template["category"],
                            template["question_template"],
                            template["requires_ticker"],
                            template["sort_order"],
                        ),
                    )
                    cur.execute(
                        "SELECT id FROM ask_templates WHERE org_id IS NULL AND template_key = %s",
                        (template["key"],),
                    )
                    row = cur.fetchone()
                    if not row:
                        continue
                    template_id = int(row[0])
                    for filing_type, item_code, weight in template["rules"]:
                        cur.execute(
                            """
                            INSERT INTO ask_template_filing_rules(template_id, filing_type, item_code, weight)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            (template_id, filing_type, item_code or "", weight),
                        )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Failed seeding ask templates")
        finally:
            self._put(conn)
