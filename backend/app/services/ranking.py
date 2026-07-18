from __future__ import annotations

import re
from collections.abc import Iterable

from ...ingestion.metadata_schema import Chunk

_TERM_RE = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", re.IGNORECASE)


def cosine_similarity(distance: float) -> float:
    """Convert Chroma cosine distance to the native [-1, 1] similarity."""

    return max(-1.0, min(1.0, 1.0 - float(distance)))


def _terms(text: str) -> set[str]:
    return {term.casefold() for term in _TERM_RE.findall(text)}


def _normalized_text(text: str) -> str:
    return " ".join(text.casefold().split())


def deduplicate_candidates(candidates: Iterable[tuple[Chunk, float]]) -> list[tuple[Chunk, float]]:
    """Keep the best dense hit for each stable ID and normalized document text."""

    best: list[tuple[int, Chunk, float]] = []
    identity_positions: dict[tuple[str, str], int] = {}
    text_positions: dict[tuple[str, str], int] = {}
    for rank, (chunk, distance) in enumerate(candidates):
        doc_id = str(chunk.metadata.get("doc_id") or "")
        identity = chunk.chunk_id or str(chunk.metadata.get("chunk_id") or "")
        identity_key = (doc_id, identity)
        text_key = (doc_id, _normalized_text(chunk.text))
        position = identity_positions.get(identity_key) if identity else None
        if position is None:
            position = text_positions.get(text_key)
        if position is None:
            position = len(best)
            best.append((rank, chunk, float(distance)))
        elif distance < best[position][2]:
            original_rank = best[position][0]
            best[position] = (original_rank, chunk, float(distance))
        identity_positions[identity_key] = position
        text_positions[text_key] = position
    return [(chunk, distance) for _, chunk, distance in sorted(best, key=lambda item: item[0])]


def rerank_candidates(
    query: str,
    candidates: Iterable[tuple[Chunk, float]],
    *,
    limit: int | None = None,
) -> list[tuple[Chunk, float]]:
    """Deterministically combine dense similarity with exact financial-term coverage."""

    deduplicated = deduplicate_candidates(candidates)
    query_terms = _terms(query)

    def score(item: tuple[Chunk, float]) -> tuple[float, float, str]:
        chunk, distance = item
        lexical = len(query_terms & _terms(chunk.text)) / len(query_terms) if query_terms else 0.0
        combined = (0.85 * cosine_similarity(distance)) + (0.15 * lexical)
        return -combined, float(distance), chunk.chunk_id

    ranked = sorted(deduplicated, key=score)
    return ranked if limit is None else ranked[: max(0, limit)]


def rerank_by_distance(chunks_with_scores: list[tuple[Chunk, float]]) -> list[tuple[Chunk, float]]:
    """Backward-compatible deterministic dense-only ordering."""

    return sorted(
        deduplicate_candidates(chunks_with_scores), key=lambda item: (item[1], item[0].chunk_id)
    )
