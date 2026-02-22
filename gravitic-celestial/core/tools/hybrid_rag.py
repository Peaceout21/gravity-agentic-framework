"""Hybrid retrieval engine with BM25 rebuild and manual RRF fusion."""

import json
import math
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

try:
    from rank_bm25 import BM25Okapi  # type: ignore
except Exception:
    BM25Okapi = None


@dataclass
class SearchResult(object):
    chunk_id: str
    text: str
    metadata: Dict[str, str]
    score: float


class HybridRAGEngine(object):
    def __init__(self, db_path="data/rag.db"):
        self.db_path = db_path
        self._bm25 = None
        self._bm25_docs = []
        self._bm25_ids = []
        self._init_db()
        self._load_bm25_index()

    def _connect(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def add_documents(self, chunks):
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            for chunk in chunks:
                chunk_id = chunk.get("id") or str(uuid.uuid4())
                conn.execute(
                    "INSERT OR REPLACE INTO chunks(id, text, metadata_json, created_at) VALUES (?, ?, ?, ?)",
                    (chunk_id, chunk["text"], json.dumps(chunk.get("metadata", {})), now),
                )
            conn.commit()
        self._load_bm25_index()

    def _load_bm25_index(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT id, text FROM chunks").fetchall()
        self._bm25_ids = [row[0] for row in rows]
        self._bm25_docs = [tokenize(row[1]) for row in rows]
        if BM25Okapi and self._bm25_docs:
            self._bm25 = BM25Okapi(self._bm25_docs)
        else:
            self._bm25 = None

    def get_chunk(self, chunk_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, text, metadata_json FROM chunks WHERE id = ?",
                (chunk_id,),
            ).fetchone()
        if not row:
            return None
        return SearchResult(chunk_id=row[0], text=row[1], metadata=json.loads(row[2]), score=0.0)

    def semantic_search(self, query, top_k=8, ticker=None):
        # Placeholder semantic scorer: token overlap with normalization.
        q_tokens = set(tokenize(query))
        if not q_tokens:
            return []
        
        with self._connect() as conn:
            if ticker:
                rows = conn.execute(
                    "SELECT id, text, metadata_json FROM chunks WHERE json_extract(metadata_json, '$.ticker') = ?",
                    (ticker.upper(),)
                ).fetchall()
            else:
                rows = conn.execute("SELECT id, text, metadata_json FROM chunks").fetchall()

        results = []
        for chunk_id, text, metadata_json in rows:
            c_tokens = set(tokenize(text))
            if not c_tokens:
                continue
            score = float(len(q_tokens.intersection(c_tokens))) / float(max(1, len(q_tokens.union(c_tokens))))
            if score > 0:
                results.append(SearchResult(chunk_id=chunk_id, text=text, metadata=json.loads(metadata_json), score=score))

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]

    def keyword_search(self, query, top_k=8, ticker=None):
        q_tokens = tokenize(query)
        if not q_tokens:
            return []

        if self._bm25 is not None and not ticker:
            # If no ticker filter, use the global BM25 index for speed
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

        # Fallback lexical scoring or ticker-filtered scoring.
        with self._connect() as conn:
            if ticker:
                rows = conn.execute(
                    "SELECT id, text, metadata_json FROM chunks WHERE json_extract(metadata_json, '$.ticker') = ?",
                    (ticker.upper(),)
                ).fetchall()
            else:
                rows = conn.execute("SELECT id, text, metadata_json FROM chunks").fetchall()

        output = []
        q_set = set(q_tokens)
        for chunk_id, text, metadata_json in rows:
            c_tokens = set(tokenize(text))
            overlap = len(q_set.intersection(c_tokens))
            if overlap:
                output.append(
                    SearchResult(
                        chunk_id=chunk_id,
                        text=text,
                        metadata=json.loads(metadata_json),
                        score=float(overlap),
                    )
                )
        output.sort(key=lambda item: item.score, reverse=True)
        return output[:top_k]

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

        ranked_ids = sorted(scores.keys(), key=lambda chunk_id: scores[chunk_id], reverse=True)[:top_k]
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

    def query(self, query_text, top_k=8, ticker=None):
        semantic = self.semantic_search(query_text, top_k=top_k, ticker=ticker)
        keyword = self.keyword_search(query_text, top_k=top_k, ticker=ticker)
        return self.reciprocal_rank_fusion(semantic, keyword, top_k=top_k)


def tokenize(text):
    if not text:
        return []
    return [token.strip().lower() for token in text.split() if token.strip()]
