"""Redis Queue (rq) wrapper for async job processing."""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Queue names
QUEUE_INGESTION = "ingestion"
QUEUE_ANALYSIS = "analysis"
QUEUE_KNOWLEDGE = "knowledge"
QUEUE_BACKFILL = "backfill"


class RedisJobQueue(object):
    """Thin wrapper around rq for the three pipeline job queues."""

    def __init__(self, redis_url):
        # type: (str) -> None
        from redis import Redis
        from rq import Queue

        self._redis = Redis.from_url(redis_url)
        self._queues = {
            QUEUE_INGESTION: Queue(QUEUE_INGESTION, connection=self._redis),
            QUEUE_ANALYSIS: Queue(QUEUE_ANALYSIS, connection=self._redis),
            QUEUE_KNOWLEDGE: Queue(QUEUE_KNOWLEDGE, connection=self._redis),
            QUEUE_BACKFILL: Queue(QUEUE_BACKFILL, connection=self._redis),
        }

    @property
    def redis(self):
        return self._redis

    def enqueue_ingestion(self, ingestion_request):
        # type: (Any) -> str
        """Enqueue an ingestion job. Returns the rq job ID."""
        payload = ingestion_request
        if isinstance(ingestion_request, list):
            payload = {"tickers": ingestion_request, "market": "US_SEC", "exchange": ""}

        job = self._queues[QUEUE_INGESTION].enqueue(
            "services.worker.handle_ingestion",
            payload,
            job_timeout="10m",
            retry=_retry(2),
        )
        logger.info("Enqueued ingestion job %s payload=%s", job.id, payload)
        return job.id

    def enqueue_analysis(self, filing_payload_dict):
        # type: (Dict[str, Any]) -> str
        """Enqueue an analysis job. Expects a serialised FilingPayload dict."""
        job = self._queues[QUEUE_ANALYSIS].enqueue(
            "services.worker.handle_analysis",
            filing_payload_dict,
            job_timeout="5m",
            retry=_retry(1),
        )
        logger.info("Enqueued analysis job %s for %s", job.id, filing_payload_dict.get("accession_number", "?"))
        return job.id

    def enqueue_knowledge(self, analysis_payload_dict):
        # type: (Dict[str, Any]) -> str
        """Enqueue a knowledge indexing job."""
        job = self._queues[QUEUE_KNOWLEDGE].enqueue(
            "services.worker.handle_knowledge",
            analysis_payload_dict,
            job_timeout="5m",
            retry=_retry(1),
        )
        logger.info("Enqueued knowledge job %s for %s", job.id, analysis_payload_dict.get("accession_number", "?"))
        return job.id

    def enqueue_backfill(self, backfill_request_dict):
        # type: (Dict[str, Any]) -> str
        job = self._queues[QUEUE_BACKFILL].enqueue(
            "services.worker.handle_backfill",
            backfill_request_dict,
            job_timeout="30m",
            retry=_retry(1),
        )
        logger.info("Enqueued backfill job %s tickers=%s", job.id, backfill_request_dict.get("tickers", []))
        return job.id

    def ping(self):
        # type: () -> bool
        """Check Redis connectivity."""
        try:
            return self._redis.ping()
        except Exception:
            return False

    def queue_depths(self):
        # type: () -> Dict[str, int]
        """Return the number of pending jobs in each queue."""
        return {name: len(q) for name, q in self._queues.items()}

    def worker_count(self):
        # type: () -> int
        """Return the number of active rq workers."""
        try:
            from rq import Worker
            workers = Worker.all(connection=self._redis)
            return len(workers)
        except Exception:
            return 0

    def failed_job_count(self):
        # type: () -> int
        """Return the total number of jobs in failed registries across all queues."""
        total = 0
        for q in self._queues.values():
            try:
                total += len(q.failed_job_registry)
            except Exception:
                pass
        return total


def _retry(count):
    # type: (int) -> Any
    """Create an rq Retry object with exponential backoff."""
    from rq import Retry
    return Retry(max=count, interval=[30, 60])
