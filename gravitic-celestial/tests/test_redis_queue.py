"""Tests for Redis job queue.

Requires a running Redis server. Set REDIS_URL to run integration tests.
Unit tests with mocks run without Redis.
"""

import os
import unittest
from unittest.mock import MagicMock, patch


class RedisQueueUnitTests(unittest.TestCase):
    """Unit tests that mock Redis/rq internals."""

    def test_import_and_queue_names(self):
        from core.adapters.redis_queue import QUEUE_ANALYSIS, QUEUE_BACKFILL, QUEUE_INGESTION, QUEUE_KNOWLEDGE
        self.assertEqual(QUEUE_INGESTION, "ingestion")
        self.assertEqual(QUEUE_ANALYSIS, "analysis")
        self.assertEqual(QUEUE_KNOWLEDGE, "knowledge")
        self.assertEqual(QUEUE_BACKFILL, "backfill")


class RedisQueueIntegrationTests(unittest.TestCase):
    """Integration tests against a real Redis instance."""

    def setUp(self):
        self.redis_url = os.getenv("REDIS_URL")
        if not self.redis_url:
            self.skipTest("REDIS_URL not set")
        try:
            import redis
            import rq
        except ImportError:
            self.skipTest("redis/rq not installed")
        try:
            client = redis.Redis.from_url(self.redis_url)
            client.ping()
        except Exception as exc:
            self.skipTest("Redis not reachable: %s" % exc)

    def test_ping(self):
        from core.adapters.redis_queue import RedisJobQueue
        queue = RedisJobQueue(self.redis_url)
        self.assertTrue(queue.ping())

    def test_enqueue_ingestion(self):
        from core.adapters.redis_queue import RedisJobQueue
        queue = RedisJobQueue(self.redis_url)
        job_id = queue.enqueue_ingestion(["MSFT"])
        self.assertIsNotNone(job_id)
        self.assertIsInstance(job_id, str)

    def test_enqueue_analysis(self):
        from core.adapters.redis_queue import RedisJobQueue
        queue = RedisJobQueue(self.redis_url)
        payload = {"ticker": "MSFT", "accession_number": "TEST-001", "filing_url": "http://x", "raw_text": "test"}
        job_id = queue.enqueue_analysis(payload)
        self.assertIsNotNone(job_id)

    def test_enqueue_knowledge(self):
        from core.adapters.redis_queue import RedisJobQueue
        queue = RedisJobQueue(self.redis_url)
        payload = {"ticker": "MSFT", "accession_number": "TEST-001", "kpis": [], "summary": {}, "guidance": []}
        job_id = queue.enqueue_knowledge(payload)
        self.assertIsNotNone(job_id)

    def test_enqueue_backfill(self):
        from core.adapters.redis_queue import RedisJobQueue
        queue = RedisJobQueue(self.redis_url)
        payload = {"tickers": ["MSFT"], "org_id": "o1", "per_ticker_limit": 2, "notify": True}
        job_id = queue.enqueue_backfill(payload)
        self.assertIsNotNone(job_id)


if __name__ == "__main__":
    unittest.main()
