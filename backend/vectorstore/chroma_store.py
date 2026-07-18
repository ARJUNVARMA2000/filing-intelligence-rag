from __future__ import annotations

import re
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from ..ingestion.index_manifest import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_NAME,
    IndexManifest,
)
from ..ingestion.metadata_schema import Chunk


class ChromaVectorStore:
    """Persistent Chroma store pinned to the packaged 384d default embedding."""

    def __init__(self, persist_directory: str, collection_name: str = "financial_docs") -> None:
        self._persist_directory = Path(persist_directory)
        self._collection_name = collection_name
        self._embedding_function = DefaultEmbeddingFunction()
        self._client = chromadb.PersistentClient(
            path=persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._create_collection()
        manifest = IndexManifest.load(self._persist_directory)
        if manifest is not None:
            manifest.validate_compatible(collection_name)

    @property
    def embedding_contract(self) -> dict[str, Any]:
        return {
            "name": DEFAULT_EMBEDDING_NAME,
            "dimension": DEFAULT_EMBEDDING_DIMENSION,
            "distance_metric": "cosine",
        }

    def _create_collection(self):
        return self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=self._embedding_function,
        )

    def reset(self) -> None:
        with suppress(ValueError):
            self._client.delete_collection(self._collection_name)
        self._collection = self._create_collection()

    def count(self) -> int:
        return int(self._collection.count())

    def validate_embedding_contract(self) -> None:
        """Fail fast if an index was built with an incompatible vector dimension."""

        if not self.count():
            return
        result = self._collection.get(limit=1, include=["embeddings"])
        embeddings = result.get("embeddings")
        if embeddings is None or len(embeddings) == 0:
            return
        dimension = len(embeddings[0])
        if dimension != DEFAULT_EMBEDDING_DIMENSION:
            raise ValueError(
                f"Index embedding dimension {dimension} is incompatible with "
                f"{DEFAULT_EMBEDDING_NAME} ({DEFAULT_EMBEDDING_DIMENSION})."
            )

    @staticmethod
    def _metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
        normalized: dict[str, str | int | float | bool] = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, str | int | float | bool):
                normalized[key] = value
            else:
                normalized[key] = str(value)
        return normalized

    def upsert(self, chunks: Sequence[Chunk]) -> None:
        if not chunks:
            return
        self._collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            metadatas=[self._metadata(chunk.metadata) for chunk in chunks],
        )

    def delete_documents(self, doc_ids: Sequence[str]) -> None:
        normalized = sorted({doc_id for doc_id in doc_ids if doc_id})
        for start in range(0, len(normalized), 100):
            batch = normalized[start : start + 100]
            if batch:
                self._collection.delete(where={"doc_id": {"$in": batch}})

    def query(
        self,
        query_text: str,
        k: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        count = self.count()
        if count == 0 or k <= 0:
            return []
        kwargs: dict[str, Any] = {
            "query_texts": [query_text],
            "n_results": min(k, count),
        }
        if where:
            kwargs["where"] = where
        result = self._collection.query(**kwargs)
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        ids = (result.get("ids") or [[]])[0]
        return [
            (
                Chunk(
                    chunk_id=str(metadata.get("chunk_id") or result_id),
                    text=str(document or ""),
                    metadata=dict(metadata or {}),
                ),
                float(distance),
            )
            for result_id, document, metadata, distance in zip(
                ids, documents, metadatas, distances, strict=False
            )
        ]

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        if not chunk_id:
            return None
        result = self._collection.get(ids=[chunk_id])
        ids = result.get("ids") or []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        if not ids or not documents or not metadatas:
            return None
        return Chunk(chunk_id=chunk_id, text=documents[0], metadata=dict(metadatas[0] or {}))

    def get_all_metadata(
        self, ticker: str | None = None, limit: int = 10_000
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        where = None
        if ticker:
            where = {"ticker": {"$in": sorted({ticker.lower(), ticker.upper()})}}
        collected: list[dict[str, Any]] = []
        offset = 0
        while len(collected) < limit:
            page_size = min(1_000, limit - len(collected))
            kwargs: dict[str, Any] = {
                "limit": page_size,
                "offset": offset,
                "include": ["metadatas"],
            }
            if where:
                kwargs["where"] = where
            result = self._collection.get(**kwargs)
            page = [dict(item or {}) for item in (result.get("metadatas") or [])]
            collected.extend(page)
            if len(page) < page_size:
                break
            offset += len(page)
        return collected

    def get_available_periods(self, ticker: str) -> list[str]:
        return sorted(
            {
                str(metadata["period"])
                for metadata in self.get_all_metadata(ticker=ticker, limit=100_000)
                if metadata.get("period")
            }
        )

    def get_all_tickers(self) -> list[str]:
        return sorted(
            {
                str(metadata["ticker"]).upper()
                for metadata in self.get_all_metadata(limit=100_000)
                if metadata.get("ticker")
            }
        )

    def get_ticker_period_map(self) -> dict[str, list[str]]:
        result: dict[str, set[str]] = {}
        for metadata in self.get_all_metadata(limit=100_000):
            ticker = str(metadata.get("ticker") or "").upper()
            period = str(metadata.get("period") or "")
            if ticker and period:
                result.setdefault(ticker, set()).add(period)
        return {ticker: sorted(periods) for ticker, periods in sorted(result.items())}

    @staticmethod
    def _period_key(metadata: dict[str, Any]) -> tuple[str, int, int]:
        date = str(
            metadata.get("event_date")
            or metadata.get("source_updated_at")
            or metadata.get("fetched_at")
            or ""
        )
        period = str(metadata.get("period") or "")
        quarter = re.fullmatch(r"Q([1-4])-(\d{4})", period, re.IGNORECASE)
        if quarter:
            return date, int(quarter.group(2)), int(quarter.group(1))
        annual = re.fullmatch(r"FY-(\d{4})", period, re.IGNORECASE)
        if annual:
            return date, int(annual.group(1)), 5
        return date, 0, 0

    def get_latest_period(self, ticker: str) -> str | None:
        metadatas = self.get_all_metadata(ticker=ticker, limit=100_000)
        if not metadatas:
            return None
        latest = max(metadatas, key=self._period_key)
        return str(latest.get("period") or "") or None

    def get_stats(self) -> dict[str, Any]:
        metadata = self.get_all_metadata(limit=100_000)
        ticker_period_map = self.get_ticker_period_map()
        sources: dict[str, int] = {}
        ticker_latest_fetch: dict[str, str | None] = {}
        for item in metadata:
            source = str(item.get("source") or "unknown")
            sources[source] = sources.get(source, 0) + 1
            ticker = str(item.get("ticker") or "").upper()
            if not ticker:
                continue
            ticker_latest_fetch.setdefault(ticker, None)
            fetched_at = str(item.get("fetched_at") or "")
            if fetched_at and (
                ticker_latest_fetch[ticker] is None or fetched_at > str(ticker_latest_fetch[ticker])
            ):
                ticker_latest_fetch[ticker] = fetched_at
        return {
            "total_chunks": self.count(),
            "total_documents": len({item.get("doc_id") for item in metadata if item.get("doc_id")}),
            "total_tickers": len(ticker_period_map),
            "total_periods": len(
                {period for periods in ticker_period_map.values() for period in periods}
            ),
            "ticker_period_map": ticker_period_map,
            "sources": sources,
            "latest_source_update": max(
                (
                    str(item["source_updated_at"])
                    for item in metadata
                    if item.get("source_updated_at")
                ),
                default=None,
            ),
            "latest_fetch": max(
                (str(item["fetched_at"]) for item in metadata if item.get("fetched_at")),
                default=None,
            ),
            "ticker_latest_fetch": dict(sorted(ticker_latest_fetch.items())),
            "embedding": self.embedding_contract,
        }
