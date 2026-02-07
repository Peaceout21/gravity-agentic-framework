"""Postgres-backed checkpoint store (drop-in for SQLiteCheckpointStore)."""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from core.graph.checkpoint import CheckpointStore

logger = logging.getLogger(__name__)


class PostgresCheckpointStore(CheckpointStore):
    """Same interface as SQLiteCheckpointStore but backed by Postgres JSONB."""

    def __init__(self, dsn):
        # type: (str) -> None
        import psycopg2
        import psycopg2.extras

        self._dsn = dsn
        self._conn = psycopg2.connect(dsn)
        # Register JSONB adapter
        psycopg2.extras.register_default_jsonb(self._conn)

    def save_state(self, graph_name, thread_id, state):
        # type: (str, str, Any) -> None
        now = datetime.utcnow()
        payload = json.loads(json.dumps(state, default=str))
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO graph_checkpoints (graph_name, thread_id, state_json, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (graph_name, thread_id)
                DO UPDATE SET state_json = EXCLUDED.state_json, updated_at = EXCLUDED.updated_at
                """,
                (graph_name, thread_id, json.dumps(payload), now),
            )
        self._conn.commit()

    def load_state(self, graph_name, thread_id):
        # type: (str, str) -> Optional[Any]
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT state_json FROM graph_checkpoints WHERE graph_name = %s AND thread_id = %s",
                (graph_name, thread_id),
            )
            row = cur.fetchone()
        if not row:
            return None
        val = row[0]
        if isinstance(val, str):
            return json.loads(val)
        return val
