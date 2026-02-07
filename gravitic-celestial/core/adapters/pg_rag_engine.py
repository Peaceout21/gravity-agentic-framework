"""Postgres + pgvector RAG engine (drop-in for HybridRAGEngine)."""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from rank_bm25 import BM25Okapi  # type: ignore
except Exception:
    BM25Okapi = None

from core.tools.hybrid_rag import SearchResult, tokenize

logger = logging.getLogger(__name__)

# Lazy-loaded sentence-transformers model
_EMBEDDER = None
_EMBED_DIM = 384


def _get_embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        from sentence_transformers import SentenceTransformer  # type: ignore
        _EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Loaded sentence-transformers all-MiniLM-L6-v2")
    return _EMBEDDER


def _embed_texts(texts):
    # type: (List[str]) -> List[List[float]]
    model = _get_embedder()
    embeddings = model.encode(texts, show_progress_bar=False)
    return [emb.tolist() for emb in embeddings]


class PostgresRAGEngine(object):
    """Same public interface as HybridRAGEngine, backed by pgvector + BM25."""

    def __init__(self, dsn):
        # type: (str) -> None
        import psycopg2

        self._dsn = dsn
        self._conn = psycopg2.connect(dsn)

        # In-memory BM25 index (same pattern as SQLite version)
        self._bm25 = None  # type: Optional[Any]
        self._bm25_docs = []  # type: List[List[str]]
        self._bm25_ids = []  # type: List[str]
        self._load_bm25_index()

    # ------------------------------------------------------------------
    # BM25 in-memory index
    # ------------------------------------------------------------------
    def _load_bm25_index(self):
        with self._conn.cursor() as cur:
            cur.execute("SELECT id, text FROM chunks")
            rows = cur.fetchall()
        self._bm25_ids = [row[0] for row in rows]
        self._bm25_docs = [tokenize(row[1]) for row in rows]
        if BM25Okapi and self._bm25_docs:
            self._bm25 = BM25Okapi(self._bm25_docs)
        else:
            self._bm25 = None

    # ------------------------------------------------------------------
    # Document ingestion
    # ------------------------------------------------------------------
    def add_documents(self, chunks):
        # type: (List[Dict[str, Any]]) -> None
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        embeddings = _embed_texts(texts)

        with self._conn.cursor() as cur:
            for chunk, emb in zip(chunks, embeddings):
                chunk_id = chunk.get("id") or str(uuid.uuid4())
                meta = json.dumps(chunk.get("metadata", {}))
                emb_str = "[%s]" % ",".join(str(v) for v in emb)
                cur.execute(
                    """
                    INSERT INTO chunks (id, text, metadata_json, embedding, created_at)
                    VALUES (%s, %s, %s, %s::vector, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET text = EXCLUDED.text,
                        metadata_json = EXCLUDED.metadata_json,
                        embedding = EXCLUDED.embedding
                    """,
                    (chunk_id, chunk["text"], meta, emb_str, datetime.utcnow()),
                )
        self._conn.commit()
        self._load_bm25_index()

    # ------------------------------------------------------------------
    # Chunk lookup
    # ------------------------------------------------------------------
    def get_chunk(self, chunk_id):
        # type: (str) -> Optional[SearchResult]
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT id, text, metadata_json FROM chunks WHERE id = %s",
                (chunk_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        meta = row[2] if isinstance(row[2], dict) else json.loads(row[2])
        return SearchResult(chunk_id=row[0], text=row[1], metadata=meta, score=0.0)

    # ------------------------------------------------------------------
    # Semantic search (pgvector cosine similarity)
    # ------------------------------------------------------------------
    def semantic_search(self, query, top_k=8):
        # type: (str, int) -> List[SearchResult]
        emb = _embed_texts([query])[0]
        emb_str = "[%s]" % ",".join(str(v) for v in emb)
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, text, metadata_json,
                       1 - (embedding <=> %s::vector) AS score
                FROM chunks
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (emb_str, emb_str, top_k),
            )
            rows = cur.fetchall()
        results = []
        for row in rows:
            meta = row[2] if isinstance(row[2], dict) else json.loads(row[2])
            results.append(
                SearchResult(chunk_id=row[0], text=row[1], metadata=meta, score=float(row[3]))
            )
        return results

    # ------------------------------------------------------------------
    # Keyword search (BM25)
    # ------------------------------------------------------------------
    def keyword_search(self, query, top_k=8):
        # type: (str, int) -> List[SearchResult]
        q_tokens = tokenize(query)
        if not q_tokens:
            return []

        if self._bm25 is not None:
            scores = self._bm25.get_scores(q_tokens)
            ranked = sorted(
                enumerate(scores),
                key=lambda pair: pair[1],
                reverse=True,
            )[:top_k]
            output = []
            for idx, score in ranked:
                result = self.get_chunk(self._bm25_ids[idx])
                if result:
                    result.score = float(score)
                    output.append(result)
            return output

        # Fallback lexical scoring
        with self._conn.cursor() as cur:
            cur.execute("SELECT id, text, metadata_json FROM chunks")
            rows = cur.fetchall()
        output = []
        q_set = set(q_tokens)
        for row in rows:
            c_tokens = set(tokenize(row[1]))
            overlap = len(q_set.intersection(c_tokens))
            if overlap:
                meta = row[2] if isinstance(row[2], dict) else json.loads(row[2])
                output.append(
                    SearchResult(chunk_id=row[0], text=row[1], metadata=meta, score=float(overlap))
                )
        output.sort(key=lambda item: item.score, reverse=True)
        return output[:top_k]

    # ------------------------------------------------------------------
    # RRF fusion (shared with SQLite version)
    # ------------------------------------------------------------------
    @staticmethod
    def reciprocal_rank_fusion(semantic_results, keyword_results, top_k=8, k=60):
        scores = {}
        lookup = {}
        for rank, result in enumerate(semantic_results, start=1):
            scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1.0 / float(k + rank)
            lookup[result.chunk_id] = result
        for rank, result in enumerate(keyword_results, start=1):
            scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1.0 / float(k + rank)
            lookup[result.chunk_id] = result
        ranked_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)[:top_k]
        fused = []
        for chunk_id in ranked_ids:
            base = lookup[chunk_id]
            fused.append(
                SearchResult(
                    chunk_id=base.chunk_id,
                    text=base.text,
                    metadata=base.metadata,
                    score=scores[chunk_id],
                )
            )
        return fused

    # ------------------------------------------------------------------
    # Full hybrid query
    # ------------------------------------------------------------------
    def query(self, query_text, top_k=8):
        # type: (str, int) -> List[SearchResult]
        semantic = self.semantic_search(query_text, top_k=top_k)
        keyword = self.keyword_search(query_text, top_k=top_k)
        return self.reciprocal_rank_fusion(semantic, keyword, top_k=top_k)
