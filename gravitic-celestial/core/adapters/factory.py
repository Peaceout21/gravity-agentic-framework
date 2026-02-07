"""Backend factory — selects SQLite or Postgres adapters based on env vars."""

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def create_backends(database_url=None, redis_url=None):
    # type: (Optional[str], Optional[str]) -> Dict[str, Any]
    """Return a dict of backend instances based on environment.

    Keys returned:
        state_manager   — StateManager or PostgresStateManager
        checkpoint_store — SQLiteCheckpointStore or PostgresCheckpointStore
        rag_engine      — HybridRAGEngine or PostgresRAGEngine
        job_queue       — None or RedisJobQueue

    When DATABASE_URL is not set, falls back to local SQLite paths.
    When REDIS_URL is not set, job_queue is None (sync mode).
    """
    database_url = database_url or os.getenv("DATABASE_URL")
    redis_url = redis_url or os.getenv("REDIS_URL")

    if database_url:
        logger.info("Using Postgres backends (DATABASE_URL set)")
        backends = _create_postgres_backends(database_url)
    else:
        logger.info("Using SQLite backends (no DATABASE_URL)")
        backends = _create_sqlite_backends()

    if redis_url:
        from core.adapters.redis_queue import RedisJobQueue
        backends["job_queue"] = RedisJobQueue(redis_url)
        logger.info("Redis job queue enabled")
    else:
        backends["job_queue"] = None

    return backends


def _create_postgres_backends(dsn):
    # type: (str) -> Dict[str, Any]
    import psycopg2

    from core.adapters.pg_checkpoint_store import PostgresCheckpointStore
    from core.adapters.pg_rag_engine import PostgresRAGEngine
    from core.adapters.pg_schema import ensure_schema
    from core.adapters.pg_state_manager import PostgresStateManager

    # Run DDL once
    conn = psycopg2.connect(dsn)
    try:
        ensure_schema(conn)
    finally:
        conn.close()

    return {
        "state_manager": PostgresStateManager(dsn),
        "checkpoint_store": PostgresCheckpointStore(dsn),
        "rag_engine": PostgresRAGEngine(dsn),
    }


def _create_sqlite_backends():
    # type: () -> Dict[str, Any]
    from core.framework.state_manager import StateManager
    from core.graph.checkpoint import SQLiteCheckpointStore
    from core.tools.hybrid_rag import HybridRAGEngine

    return {
        "state_manager": StateManager(db_path="data/state.db"),
        "checkpoint_store": SQLiteCheckpointStore(db_path="data/checkpoints.db"),
        "rag_engine": HybridRAGEngine(db_path="data/rag.db"),
    }
