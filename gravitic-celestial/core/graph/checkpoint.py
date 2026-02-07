"""SQLite-backed checkpoint store for graph durability."""

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional


class CheckpointStore(object):
    def save_state(self, graph_name, thread_id, state):
        raise NotImplementedError

    def load_state(self, graph_name, thread_id):
        raise NotImplementedError


class SQLiteCheckpointStore(CheckpointStore):
    def __init__(self, db_path="data/checkpoints.db"):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_checkpoints (
                    graph_name TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(graph_name, thread_id)
                )
                """
            )
            conn.commit()

    def save_state(self, graph_name, thread_id, state):
        now = datetime.utcnow().isoformat()
        payload = json.dumps(state, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO graph_checkpoints(graph_name, thread_id, state_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(graph_name, thread_id)
                DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at
                """,
                (graph_name, thread_id, payload, now),
            )
            conn.commit()

    def load_state(self, graph_name, thread_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM graph_checkpoints WHERE graph_name = ? AND thread_id = ?",
                (graph_name, thread_id),
            ).fetchone()
        if not row:
            return None
        return json.loads(row[0])
