"""Schema retrieval: vector, hybrid (vector + BM25) and hybrid + cross-encoder rerank.

The three modes exist so the benchmark can measure what each stage adds.
"""

import re
from functools import lru_cache
from typing import Literal

import psycopg
from pgvector.psycopg import register_vector
from rank_bm25 import BM25Okapi

from nlagent.catalogue import ColumnDoc, fetch_foreign_keys, load_catalogue
from nlagent.config import settings

RetrievalMode = Literal["vector", "hybrid", "hybrid_rerank"]
RRF_K = 60  # standard constant for reciprocal rank fusion
CANDIDATE_POOL = 100  # candidates each retriever contributes before fusing and reranking


@lru_cache(maxsize=1)
def _embedder():
    from fastembed import TextEmbedding

    return TextEmbedding(settings.embedding_model)


def embed_texts(texts: list[str]) -> list[list[float]]:
    return [vector.tolist() for vector in _embedder().embed(texts)]


@lru_cache(maxsize=1)
def _reranker():
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(settings.reranker_model)


@lru_cache(maxsize=1)
def _catalogue() -> list[ColumnDoc]:
    return load_catalogue()


@lru_cache(maxsize=1)
def _bm25() -> BM25Okapi:
    return BM25Okapi([_tokenise(doc.text) for doc in _catalogue()])


def _tokenise(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def vector_search(question: str, k: int) -> list[ColumnDoc]:
    query_vector = embed_texts([question])[0]
    with psycopg.connect(settings.database_url) as conn:
        register_vector(conn)
        rows = conn.execute(
            "select table_name, column_name from catalog.columns "
            "order by embedding <=> %s::vector limit %s",
            (query_vector, k),
        ).fetchall()
    by_key = {doc.key: doc for doc in _catalogue()}
    return [by_key[f"{table}.{column}"] for table, column in rows]


def bm25_search(question: str, k: int) -> list[ColumnDoc]:
    scores = _bm25().get_scores(_tokenise(question))
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    return [_catalogue()[i] for i in ranked]


def reciprocal_rank_fusion(rankings: list[list[ColumnDoc]], k: int) -> list[ColumnDoc]:
    """Merge ranked lists: a column scores higher the nearer the top it appears in each list."""
    scores: dict[str, float] = {}
    docs: dict[str, ColumnDoc] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking):
            scores[doc.key] = scores.get(doc.key, 0.0) + 1.0 / (RRF_K + rank + 1)
            docs[doc.key] = doc
    best = sorted(scores, key=scores.get, reverse=True)[:k]
    return [docs[key] for key in best]


def rerank(question: str, candidates: list[ColumnDoc], k: int) -> list[ColumnDoc]:
    scores = list(_reranker().rerank(question, [doc.text for doc in candidates]))
    order = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)[:k]
    return [candidates[i] for i in order]


def retrieve_columns(question: str, mode: RetrievalMode = "hybrid_rerank", k: int = 25) -> list[ColumnDoc]:
    """Return the k columns most relevant to the question."""
    pool = CANDIDATE_POOL
    if mode == "vector":
        return vector_search(question, k)
    fused = reciprocal_rank_fusion([vector_search(question, pool), bm25_search(question, pool)], pool)
    if mode == "hybrid":
        return fused[:k]
    return rerank(question, fused, k)


@lru_cache(maxsize=1)
def _foreign_keys() -> list[tuple[str, str, str, str]]:
    with psycopg.connect(settings.admin_database_url) as conn:
        return fetch_foreign_keys(conn)


def _inferred_view_joins() -> list[tuple[str, str, str, str]]:
    """Views carry no foreign keys, so join `<name>_id` columns to table `<name>` by convention."""
    tables = {doc.table for doc in _catalogue()}
    joins = []
    for doc in _catalogue():
        referenced = doc.column.removesuffix("_id")
        if doc.column.endswith("_id") and referenced in tables and doc.table != referenced:
            joins.append((doc.table, doc.column, referenced, "id"))
    return joins


def render_schema(columns: list[ColumnDoc]) -> str:
    """Prompt text for the retrieved columns, plus join keys so the model can connect tables."""
    from nlagent.catalogue import TABLE_NOTES

    wanted: dict[str, dict[str, str]] = {}
    for doc in columns:
        wanted.setdefault(doc.table, {})[doc.column] = doc.data_type
    types = {doc.key: doc.data_type for doc in _catalogue()}

    joins = []
    for table, column, ref_table, ref_column in _foreign_keys() + _inferred_view_joins():
        if table in wanted and ref_table in wanted:
            wanted[table].setdefault(column, types[f"{table}.{column}"])
            wanted[ref_table].setdefault(ref_column, types[f"{ref_table}.{ref_column}"])
            joins.append(f"{table}.{column} = {ref_table}.{ref_column}")

    lines = []
    for table, cols in wanted.items():
        lines.append(f"TABLE {table}" + (f"  -- {TABLE_NOTES[table]}" if table in TABLE_NOTES else ""))
        lines.extend(f"  {name} {dtype}" for name, dtype in cols.items())
    if joins:
        lines.append("JOINS: " + "; ".join(joins))
    return "\n".join(lines)


def render_full_schema() -> str:
    """Every column of every table. Used by the full-schema baseline configuration."""
    return render_schema(_catalogue())
