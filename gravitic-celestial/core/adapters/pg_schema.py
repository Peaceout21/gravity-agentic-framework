"""Postgres DDL for production deployment (pgvector + HNSW)."""

import logging

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
-- pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Filing processing state
CREATE TABLE IF NOT EXISTS filings (
    accession_number TEXT PRIMARY KEY,
    ticker           TEXT NOT NULL,
    filing_url       TEXT NOT NULL,
    status           TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_filings_updated_at ON filings (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_filings_ticker ON filings (ticker);

-- Event log
CREATE TABLE IF NOT EXISTS events (
    id         BIGSERIAL PRIMARY KEY,
    topic      TEXT NOT NULL,
    source     TEXT NOT NULL,
    payload    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- User watchlists
CREATE TABLE IF NOT EXISTS watchlists (
    org_id    TEXT NOT NULL DEFAULT 'default',
    user_id    TEXT NOT NULL,
    ticker     TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_watchlists_ticker ON watchlists (ticker);

-- In-app notifications
CREATE TABLE IF NOT EXISTS notifications (
    id                BIGSERIAL PRIMARY KEY,
    org_id            TEXT NOT NULL DEFAULT 'default',
    user_id           TEXT NOT NULL,
    ticker            TEXT NOT NULL,
    accession_number  TEXT NOT NULL,
    notification_type TEXT NOT NULL,
    title             TEXT NOT NULL,
    body              TEXT NOT NULL,
    is_read           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notifications_user_created
    ON notifications (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_user_unread
    ON notifications (user_id, is_read);

ALTER TABLE watchlists ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'default';
CREATE UNIQUE INDEX IF NOT EXISTS uq_watchlists_org_user_ticker
    ON watchlists (org_id, user_id, ticker);
CREATE INDEX IF NOT EXISTS idx_watchlists_org_ticker
    ON watchlists (org_id, ticker);
CREATE INDEX IF NOT EXISTS idx_notifications_org_user_created
    ON notifications (org_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_org_user_unread
    ON notifications (org_id, user_id, is_read);

-- Graph execution checkpoints
CREATE TABLE IF NOT EXISTS graph_checkpoints (
    graph_name TEXT NOT NULL,
    thread_id  TEXT NOT NULL,
    state_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (graph_name, thread_id)
);

-- RAG chunks with vector embeddings
CREATE TABLE IF NOT EXISTS chunks (
    id            TEXT PRIMARY KEY,
    text          TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}',
    embedding     vector(384),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);
"""


def ensure_schema(conn):
    """Execute all DDL statements on the given psycopg2 connection.

    Intended to run once at startup. All statements use IF NOT EXISTS /
    IF NOT EXISTS so they are safe to re-run.
    """
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()
    logger.info("Postgres schema ensured")
