from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ...ingestion.metadata_schema import Chunk
from ..schemas import Citation
from .highlight import append_pdf_fragment, build_search_phrase
from .ranking import cosine_similarity

_SOURCE_GROUP_RE = re.compile(r"\[((?:S\d+\s*,?\s*)+)\]", re.IGNORECASE)
_SOURCE_ID_RE = re.compile(r"S(\d+)", re.IGNORECASE)


def extract_source_indices(answer: str) -> list[int]:
    result: list[int] = []
    for group in _SOURCE_GROUP_RE.finditer(answer):
        for value in _SOURCE_ID_RE.findall(group.group(1)):
            index = int(value) - 1
            if index >= 0 and index not in result:
                result.append(index)
    return result


def select_cited_chunks(
    answer: str,
    chunks_with_scores: list[tuple[Chunk, float]],
) -> tuple[list[tuple[Chunk, float]], dict[str, Any]]:
    requested = extract_source_indices(answer)
    valid = [index for index in requested if index < len(chunks_with_scores)]
    invalid = [f"S{index + 1}" for index in requested if index >= len(chunks_with_scores)]
    if valid:
        return [chunks_with_scores[index] for index in valid], {
            "mode": "answer_bound",
            "source_ids": [f"S{index + 1}" for index in valid],
            "invalid_source_ids": invalid,
        }
    return [], {
        "mode": "invalid" if invalid else "missing",
        "source_ids": [],
        "invalid_source_ids": invalid,
    }


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value) if value not in (None, "") else 0
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _build_highlight_url(chunk: Chunk) -> str | None:
    metadata = chunk.metadata
    doc_id = str(metadata.get("doc_id") or "")
    chunk_id = str(metadata.get("chunk_id") or chunk.chunk_id or "")
    local_path = str(metadata.get("local_path") or "")
    if local_path and doc_id and chunk_id:
        endpoint = "viewer" if Path(local_path).suffix.lower() == ".pdf" else "file"
        return f"/documents/{doc_id}/chunks/{chunk_id}/{endpoint}"
    source_url = str(metadata.get("source_url") or "")
    if not source_url:
        return None
    if source_url.lower().split("?", 1)[0].endswith(".pdf"):
        return append_pdf_fragment(
            source_url,
            _positive_int(metadata.get("page_start")),
            build_search_phrase(chunk.text),
        )
    return source_url


def build_citations(chunks_with_scores: list[tuple[Chunk, float]]) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[tuple[str, str]] = set()
    for chunk, distance in chunks_with_scores:
        metadata = chunk.metadata
        chunk_id = str(metadata.get("chunk_id") or chunk.chunk_id or "")
        key = (str(metadata.get("doc_id") or ""), chunk_id)
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            Citation(
                doc_id=key[0],
                doc_title=str(metadata.get("title") or ""),
                ticker=str(metadata.get("ticker") or "").upper(),
                filing_type=str(metadata.get("filing_type") or ""),
                period=str(metadata.get("period") or ""),
                section=str(metadata.get("section") or ""),
                page=_positive_int(metadata.get("page_start")),
                line_start=_positive_int(metadata.get("line_start")),
                line_end=_positive_int(metadata.get("line_end")),
                table_id=str(metadata.get("table_id") or "") or None,
                source_url=str(metadata.get("source_url") or "") or None,
                chunk_id=chunk_id or None,
                highlight_url=_build_highlight_url(chunk),
                text=chunk.text[:500] if chunk.text else None,
                relevance_score=max(0.0, min(1.0, cosine_similarity(distance))),
            )
        )
    return citations
