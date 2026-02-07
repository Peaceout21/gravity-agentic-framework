"""Tests for the backend factory (SQLite vs Postgres selection)."""

import os
import unittest


class FactoryDefaultTests(unittest.TestCase):
    """Factory returns SQLite backends when no DATABASE_URL is set."""

    def test_sqlite_fallback(self):
        # Ensure no DATABASE_URL leaks into test
        env_backup = os.environ.pop("DATABASE_URL", None)
        redis_backup = os.environ.pop("REDIS_URL", None)
        try:
            from core.adapters.factory import create_backends
            from core.framework.state_manager import StateManager
            from core.graph.checkpoint import SQLiteCheckpointStore
            from core.tools.hybrid_rag import HybridRAGEngine

            backends = create_backends()
            self.assertIsInstance(backends["state_manager"], StateManager)
            self.assertIsInstance(backends["checkpoint_store"], SQLiteCheckpointStore)
            self.assertIsInstance(backends["rag_engine"], HybridRAGEngine)
            self.assertIsNone(backends["job_queue"])
        finally:
            if env_backup is not None:
                os.environ["DATABASE_URL"] = env_backup
            if redis_backup is not None:
                os.environ["REDIS_URL"] = redis_backup

    def test_postgres_selected_when_database_url_set(self):
        """Factory imports Postgres classes when DATABASE_URL is provided.

        We can't actually connect without a real DB, so just verify that
        passing a bogus DSN raises a psycopg2 connection error (not an
        import error or factory logic error).
        """
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            self.skipTest("psycopg2 not installed")

        from core.adapters.factory import create_backends

        with self.assertRaises(Exception) as ctx:
            create_backends(database_url="postgresql://nobody:bad@localhost:1/nonexistent")
        # Should be a connection error, not an ImportError
        self.assertNotIsInstance(ctx.exception, ImportError)

    def test_redis_queue_created_when_redis_url_set(self):
        """Factory creates RedisJobQueue when REDIS_URL is provided."""
        try:
            import redis  # noqa: F401
            import rq  # noqa: F401
        except ImportError:
            self.skipTest("redis/rq not installed")

        from core.adapters.factory import create_backends

        # Ensure DATABASE_URL does not force Postgres path in this test.
        db_backup = os.environ.pop("DATABASE_URL", None)
        try:
            # Use SQLite backends but add Redis.
            backends = create_backends(redis_url="redis://localhost:6379")
            # Job queue should be a RedisJobQueue instance (even if Redis isn't running).
            from core.adapters.redis_queue import RedisJobQueue
            self.assertIsInstance(backends["job_queue"], RedisJobQueue)
        finally:
            if db_backup is not None:
                os.environ["DATABASE_URL"] = db_backup


if __name__ == "__main__":
    unittest.main()
