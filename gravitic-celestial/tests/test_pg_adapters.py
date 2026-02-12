"""Integration tests for Postgres adapters.

Requires a running Postgres with pgvector. Set DATABASE_URL to run.
Skipped automatically when DATABASE_URL is not set or psycopg2 is missing.
"""

import json
import os
import unittest

DATABASE_URL = os.getenv("DATABASE_URL")


def _requires_postgres(test_func):
    """Decorator: skip if no Postgres connection available."""
    def wrapper(self):
        if not DATABASE_URL:
            self.skipTest("DATABASE_URL not set")
        try:
            import psycopg2
        except ImportError:
            self.skipTest("psycopg2 not installed")
        try:
            conn = psycopg2.connect(DATABASE_URL, connect_timeout=1)
            conn.close()
        except Exception as exc:
            self.skipTest("Postgres not reachable: %s" % exc)
        return test_func(self)
    wrapper.__name__ = test_func.__name__
    return wrapper


class PostgresSchemaTests(unittest.TestCase):
    @_requires_postgres
    def test_ensure_schema_is_idempotent(self):
        import psycopg2
        from core.adapters.pg_schema import ensure_schema

        conn = psycopg2.connect(DATABASE_URL)
        try:
            ensure_schema(conn)
            ensure_schema(conn)  # second call should not error
            with conn.cursor() as cur:
                cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                tables = {row[0] for row in cur.fetchall()}
            self.assertIn("filings", tables)
            self.assertIn("events", tables)
            self.assertIn("graph_checkpoints", tables)
            self.assertIn("chunks", tables)
            self.assertIn("watchlists", tables)
            self.assertIn("notifications", tables)
        finally:
            conn.close()


class PostgresStateManagerTests(unittest.TestCase):
    @_requires_postgres
    def test_upsert_and_list(self):
        from core.adapters.pg_state_manager import PostgresStateManager

        sm = PostgresStateManager(DATABASE_URL)
        acc = "TEST-0001-00-000001"

        # Clean up from prior run
        conn = sm._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM filings WHERE accession_number = %s", (acc,))
            conn.commit()
        finally:
            sm._put(conn)

        self.assertFalse(sm.has_accession(acc))
        sm.mark_ingested(acc, "TEST", "http://test")
        self.assertTrue(sm.has_accession(acc))

        sm.mark_analyzed(acc, "TEST", "http://test")
        filings = sm.list_recent_filings(limit=5)
        found = [f for f in filings if f["accession_number"] == acc]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["status"], "ANALYZED")

        # Cleanup
        conn = sm._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM filings WHERE accession_number = %s", (acc,))
            conn.commit()
        finally:
            sm._put(conn)

    @_requires_postgres
    def test_log_event(self):
        from core.adapters.pg_state_manager import PostgresStateManager

        sm = PostgresStateManager(DATABASE_URL)
        sm.log_event("TEST_TOPIC", "test_source", "test payload")

    @_requires_postgres
    def test_watchlist_and_notifications(self):
        from core.adapters.pg_state_manager import PostgresStateManager

        sm = PostgresStateManager(DATABASE_URL)
        org_id = "org-test"
        user_id = "test-user"
        ticker = "MSFT"

        conn = sm._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM notifications WHERE org_id = %s AND user_id = %s", (org_id, user_id))
                cur.execute("DELETE FROM watchlists WHERE org_id = %s AND user_id = %s", (org_id, user_id))
            conn.commit()
        finally:
            sm._put(conn)

        sm.add_watchlist_ticker(org_id, user_id, ticker)
        self.assertEqual(sm.list_watchlist_subscribers(org_id, ticker), [user_id])

        sm.create_notification(
            org_id=org_id,
            user_id=user_id,
            ticker=ticker,
            accession_number="TEST-ACC",
            notification_type="FILING_FOUND",
            title="title",
            body="body",
        )
        notifications = sm.list_notifications(org_id, user_id, limit=10, unread_only=True)
        self.assertEqual(len(notifications), 1)
        notification_id = notifications[0]["id"]
        self.assertTrue(sm.mark_notification_read(org_id, user_id, notification_id))
        unread = sm.list_notifications(org_id, user_id, limit=10, unread_only=True)
        self.assertEqual(len(unread), 0)

    @_requires_postgres
    def test_ask_templates_and_runs(self):
        from core.adapters.pg_state_manager import PostgresStateManager

        sm = PostgresStateManager(DATABASE_URL)
        org_id = "org-template-test"
        user_id = "user-template-test"
        templates = sm.list_ask_templates(org_id, user_id)
        self.assertGreaterEqual(len(templates), 1)
        template = templates[0]
        rules = sm.list_ask_template_rules(template["id"])
        self.assertGreaterEqual(len(rules), 1)

        conn = sm._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ask_template_runs WHERE org_id = %s AND user_id = %s", (org_id, user_id))
            conn.commit()
        finally:
            sm._put(conn)

        run_id = sm.create_ask_template_run(
            org_id=org_id,
            user_id=user_id,
            template_id=template["id"],
            ticker="MSFT",
            rendered_question="What changed for MSFT?",
            relevance_label="High relevance",
            coverage_brief="Based on analyzed filings: 10-Q (2026-01-01).",
            answer_markdown="Answer",
            citations=["chunk-1"],
            latency_ms=100,
        )
        self.assertGreater(run_id, 0)
        runs = sm.list_ask_template_runs(org_id, user_id, limit=5)
        self.assertEqual(len(runs), 1)


class PostgresCheckpointStoreTests(unittest.TestCase):
    @_requires_postgres
    def test_save_and_load(self):
        from core.adapters.pg_checkpoint_store import PostgresCheckpointStore

        store = PostgresCheckpointStore(DATABASE_URL)
        state = {"ok": True, "count": 42, "nested": {"key": "value"}}
        store.save_state("test_graph", "test_thread", state)

        loaded = store.load_state("test_graph", "test_thread")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["ok"], True)
        self.assertEqual(loaded["count"], 42)
        self.assertEqual(loaded["nested"]["key"], "value")

    @_requires_postgres
    def test_load_missing_returns_none(self):
        from core.adapters.pg_checkpoint_store import PostgresCheckpointStore

        store = PostgresCheckpointStore(DATABASE_URL)
        result = store.load_state("nonexistent", "nope")
        self.assertIsNone(result)

    @_requires_postgres
    def test_upsert_overwrites(self):
        from core.adapters.pg_checkpoint_store import PostgresCheckpointStore

        store = PostgresCheckpointStore(DATABASE_URL)
        store.save_state("test_graph", "upsert_thread", {"v": 1})
        store.save_state("test_graph", "upsert_thread", {"v": 2})
        loaded = store.load_state("test_graph", "upsert_thread")
        self.assertEqual(loaded["v"], 2)


class PostgresRAGEngineTests(unittest.TestCase):
    @_requires_postgres
    def test_add_and_query(self):
        try:
            from sentence_transformers import SentenceTransformer  # noqa: F401
        except ImportError:
            self.skipTest("sentence-transformers not installed")

        from core.adapters.pg_rag_engine import PostgresRAGEngine

        engine = PostgresRAGEngine(DATABASE_URL)

        # Clean test data
        with engine._conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE id LIKE 'test-%%'")
        engine._conn.commit()

        chunks = [
            {"id": "test-1", "text": "Microsoft reported revenue of 56 billion dollars", "metadata": {"ticker": "MSFT"}},
            {"id": "test-2", "text": "Apple announced earnings per share of 1.52", "metadata": {"ticker": "AAPL"}},
            {"id": "test-3", "text": "Google Cloud revenue grew 28 percent year over year", "metadata": {"ticker": "GOOGL"}},
        ]
        engine.add_documents(chunks)

        # Semantic search
        results = engine.semantic_search("Microsoft revenue", top_k=3)
        self.assertGreater(len(results), 0)
        # The Microsoft chunk should rank highly
        chunk_ids = [r.chunk_id for r in results]
        self.assertIn("test-1", chunk_ids)

        # Keyword search
        kw_results = engine.keyword_search("revenue", top_k=3)
        self.assertGreater(len(kw_results), 0)

        # Full hybrid query
        hybrid_results = engine.query("Microsoft revenue", top_k=3)
        self.assertGreater(len(hybrid_results), 0)

        # get_chunk
        chunk = engine.get_chunk("test-1")
        self.assertIsNotNone(chunk)
        self.assertIn("Microsoft", chunk.text)

        # Cleanup
        with engine._conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE id LIKE 'test-%%'")
        engine._conn.commit()

    @_requires_postgres
    def test_rrf_fusion_matches_sqlite(self):
        """RRF static method should give same results as SQLite version."""
        from core.adapters.pg_rag_engine import PostgresRAGEngine
        from core.tools.hybrid_rag import HybridRAGEngine, SearchResult

        semantic = [
            SearchResult(chunk_id="a", text="A", metadata={}, score=0.9),
            SearchResult(chunk_id="b", text="B", metadata={}, score=0.8),
        ]
        keyword = [
            SearchResult(chunk_id="b", text="B", metadata={}, score=11.0),
            SearchResult(chunk_id="a", text="A", metadata={}, score=10.0),
        ]

        pg_fused = PostgresRAGEngine.reciprocal_rank_fusion(semantic, keyword, top_k=2)
        sqlite_fused = HybridRAGEngine.reciprocal_rank_fusion(semantic, keyword, top_k=2)

        self.assertEqual(len(pg_fused), len(sqlite_fused))
        for pg_r, sq_r in zip(pg_fused, sqlite_fused):
            self.assertEqual(pg_r.chunk_id, sq_r.chunk_id)
            self.assertAlmostEqual(pg_r.score, sq_r.score, places=6)


if __name__ == "__main__":
    unittest.main()
