from __future__ import annotations

from typing import Any

from ...ingestion.metadata_schema import Chunk
from ...vectorstore.chroma_store import ChromaVectorStore
from .ranking import cosine_similarity, rerank_candidates


class Retriever:
    def __init__(self, vector_store: ChromaVectorStore) -> None:
        self._store = vector_store

    def retrieve(
        self,
        query: str,
        *,
        k: int = 10,
        tickers: list[str] | None = None,
        period: str | None = None,
        min_similarity: float | None = None,
        allow_blank_query: bool = False,
    ) -> list[tuple[Chunk, float]]:
        if not query.strip() and not allow_blank_query:
            return []
        final_k = max(1, min(int(k), 50))
        conditions: list[dict[str, Any]] = []
        normalized_tickers = sorted(
            {ticker.strip().lower() for ticker in tickers or [] if ticker.strip()}
        )
        if normalized_tickers:
            conditions.append({"ticker": {"$in": normalized_tickers}})
        if period:
            conditions.append({"period": period})
        where: dict[str, Any] = {}
        if len(conditions) == 1:
            where = conditions[0]
        elif conditions:
            where = {"$and": conditions}

        candidate_k = min(100, max(final_k * 4, 24))
        candidates = self._store.query(query_text=query, k=candidate_k, where=where)
        if min_similarity is not None:
            candidates = [
                (chunk, distance)
                for chunk, distance in candidates
                if cosine_similarity(distance) >= min_similarity
            ]
        return rerank_candidates(query, candidates, limit=final_k)
