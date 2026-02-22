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
    dead_letter_reason TEXT,
    last_error         TEXT,
    replay_count       INTEGER NOT NULL DEFAULT 0,
    last_replay_at     TIMESTAMPTZ,
    market           TEXT NOT NULL DEFAULT 'US_SEC',
    exchange         TEXT,
    issuer_id        TEXT,
    source           TEXT,
    source_event_id  TEXT,
    document_type    TEXT,
    currency         TEXT,
    filing_type      TEXT,
    item_code        TEXT,
    filing_date      DATE,
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
    market     TEXT NOT NULL DEFAULT 'US_SEC',
    exchange   TEXT,
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
    market            TEXT NOT NULL DEFAULT 'US_SEC',
    exchange          TEXT,
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
ALTER TABLE filings ADD COLUMN IF NOT EXISTS filing_type TEXT;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS item_code TEXT;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS filing_date DATE;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS market TEXT NOT NULL DEFAULT 'US_SEC';
ALTER TABLE filings ADD COLUMN IF NOT EXISTS dead_letter_reason TEXT;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS replay_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS last_replay_at TIMESTAMPTZ;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS exchange TEXT;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS issuer_id TEXT;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS source_event_id TEXT;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS document_type TEXT;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS currency TEXT;
ALTER TABLE watchlists ADD COLUMN IF NOT EXISTS market TEXT NOT NULL DEFAULT 'US_SEC';
ALTER TABLE watchlists ADD COLUMN IF NOT EXISTS exchange TEXT;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS market TEXT NOT NULL DEFAULT 'US_SEC';
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS exchange TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_watchlists_org_user_ticker
    ON watchlists (org_id, user_id, ticker);
CREATE INDEX IF NOT EXISTS idx_watchlists_org_ticker
    ON watchlists (org_id, ticker);
CREATE INDEX IF NOT EXISTS idx_notifications_org_user_created
    ON notifications (org_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_org_user_unread
    ON notifications (org_id, user_id, is_read);
CREATE UNIQUE INDEX IF NOT EXISTS uq_filings_market_source_event
    ON filings (market, source_event_id)
    WHERE source_event_id IS NOT NULL AND source_event_id <> '';
CREATE INDEX IF NOT EXISTS idx_filings_market_updated_at
    ON filings (market, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_filings_market_ticker
    ON filings (market, ticker);

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

-- Quick ask templates
CREATE TABLE IF NOT EXISTS ask_templates (
    id                BIGSERIAL PRIMARY KEY,
    org_id            TEXT,
    template_key      TEXT NOT NULL,
    title             TEXT NOT NULL,
    description       TEXT NOT NULL,
    category          TEXT NOT NULL,
    question_template TEXT NOT NULL,
    requires_ticker   BOOLEAN NOT NULL DEFAULT TRUE,
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order        INTEGER NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ask_templates_org_key
    ON ask_templates (COALESCE(org_id, '__global__'), template_key);

CREATE TABLE IF NOT EXISTS ask_template_filing_rules (
    id          BIGSERIAL PRIMARY KEY,
    template_id BIGINT NOT NULL REFERENCES ask_templates(id) ON DELETE CASCADE,
    filing_type TEXT NOT NULL,
    item_code   TEXT NOT NULL DEFAULT '',
    weight      DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ask_template_rules_template_id
    ON ask_template_filing_rules (template_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ask_template_rules_unique
    ON ask_template_filing_rules (template_id, filing_type, item_code);

CREATE TABLE IF NOT EXISTS ask_template_runs (
    id                BIGSERIAL PRIMARY KEY,
    org_id            TEXT NOT NULL,
    user_id           TEXT NOT NULL,
    template_id       BIGINT NOT NULL REFERENCES ask_templates(id) ON DELETE CASCADE,
    ticker            TEXT,
    rendered_question TEXT NOT NULL,
    relevance_label   TEXT NOT NULL,
    coverage_brief    TEXT NOT NULL,
    answer_markdown   TEXT NOT NULL,
    citations_json    JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence        DOUBLE PRECISION NOT NULL DEFAULT 0,
    derivation_trace_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    latency_ms        INTEGER NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ask_template_runs_org_user_created
    ON ask_template_runs (org_id, user_id, created_at DESC);
ALTER TABLE ask_template_runs ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE ask_template_runs ADD COLUMN IF NOT EXISTS derivation_trace_json JSONB NOT NULL DEFAULT '[]'::jsonb;
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
