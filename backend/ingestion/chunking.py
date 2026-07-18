from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .metadata_schema import Block, Chunk, Document, Line

_TOKEN_RE = re.compile(r"\w+(?:[.-]\w+)*|[^\w\s]", re.UNICODE)


@dataclass
class ChunkingConfig:
    """Deterministic limits for the Chroma default embedding pipeline.

    The bundled MiniLM embedding function does not expose its tokenizer through
    Chroma. ``max_tokens`` is therefore a conservative lexical-token budget,
    not a claim about an OpenAI tokenizer.
    """

    max_tokens: int = 800
    overlap_tokens: int = 120
    min_chunk_size: int = 80
    max_block_tokens: int = 500
    keep_tables_intact: bool = True
    keep_charts_intact: bool = True
    add_document_context: bool = True
    add_section_headers: bool = True
    use_semantic_boundaries: bool = True
    separators: list[str] | None = None

    def __post_init__(self) -> None:
        if self.max_tokens < 1 or self.max_block_tokens < 1:
            raise ValueError("Chunk token limits must be positive.")
        if not 0 <= self.overlap_tokens < self.max_tokens:
            raise ValueError("overlap_tokens must be non-negative and below max_tokens.")
        if self.min_chunk_size < 0:
            raise ValueError("min_chunk_size cannot be negative.")
        if self.separators is None:
            self.separators = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "]


@dataclass(frozen=True)
class _BlockSlice:
    block: Block
    text: str
    line_start: int | None
    line_end: int | None

    @property
    def token_count(self) -> int:
        return _token_count(self.text)


def _token_count(text: str) -> int:
    return len(_TOKEN_RE.findall(text))


def _split_words(text: str, budget: int) -> list[str]:
    words = text.split()
    return [" ".join(words[start : start + budget]) for start in range(0, len(words), budget)]


def _slice_block(block: Block, config: ChunkingConfig) -> list[_BlockSlice]:
    text = block.text.strip()
    if not text:
        return []

    line_numbers = [line.line_number for line in block.lines]
    line_start = min(line_numbers, default=None)
    line_end = max(line_numbers, default=None)
    keep_atomic = (block.type == "table" and config.keep_tables_intact) or (
        block.type == "chart" and config.keep_charts_intact
    )
    if keep_atomic or _token_count(text) <= config.max_block_tokens:
        return [_BlockSlice(block, text, line_start, line_end)]

    if not block.lines:
        return [
            _BlockSlice(block, part, None, None)
            for part in _split_words(text, config.max_block_tokens)
            if part
        ]

    slices: list[_BlockSlice] = []
    buffered: list[Line] = []
    buffered_tokens = 0

    def flush() -> None:
        nonlocal buffered, buffered_tokens
        if not buffered:
            return
        slices.append(
            _BlockSlice(
                block=block,
                text="\n".join(line.text for line in buffered).strip(),
                line_start=buffered[0].line_number,
                line_end=buffered[-1].line_number,
            )
        )
        buffered = []
        buffered_tokens = 0

    for line in block.lines:
        line_tokens = _token_count(line.text)
        if line_tokens > config.max_block_tokens:
            flush()
            for part in _split_words(line.text, config.max_block_tokens):
                slices.append(_BlockSlice(block, part, line.line_number, line.line_number))
            continue
        if buffered and buffered_tokens + line_tokens > config.max_block_tokens:
            flush()
        buffered.append(line)
        buffered_tokens += line_tokens
    flush()
    return [item for item in slices if item.text]


def _same_scope(left: _BlockSlice, right: _BlockSlice) -> bool:
    if left.block.type in {"table", "chart"} or right.block.type in {"table", "chart"}:
        return False
    return (
        left.block.page_number == right.block.page_number
        and left.block.section == right.block.section
    )


def _group_slices(slices: Iterable[_BlockSlice], config: ChunkingConfig) -> list[list[_BlockSlice]]:
    groups: list[list[_BlockSlice]] = []
    current: list[_BlockSlice] = []
    current_tokens = 0

    for item in slices:
        must_flush = bool(
            current
            and (
                not _same_scope(current[-1], item)
                or current_tokens + item.token_count > config.max_tokens
            )
        )
        if must_flush:
            groups.append(current)
            overlap: list[_BlockSlice] = []
            overlap_size = 0
            for previous in reversed(current):
                if not _same_scope(previous, item):
                    break
                if overlap_size + previous.token_count > config.overlap_tokens:
                    break
                overlap.insert(0, previous)
                overlap_size += previous.token_count
            current = overlap
            current_tokens = overlap_size
        current.append(item)
        current_tokens += item.token_count

    if current:
        groups.append(current)
    return groups


def _common_value(values: Iterable[str | None]) -> str:
    normalized = [value for value in values if value]
    return normalized[0] if normalized and len(set(normalized)) == 1 else ""


def _document_context(document: Document, config: ChunkingConfig) -> list[str]:
    metadata = document.metadata
    context: list[str] = []
    if config.add_document_context:
        identity = " | ".join(
            value
            for value in (
                metadata.ticker.upper(),
                metadata.period,
                metadata.filing_type,
                metadata.title,
            )
            if value
        )
        if identity:
            context.append(f"Document: {identity}")
    return context


def _build_chunk(
    document: Document, items: list[_BlockSlice], index: int, config: ChunkingConfig
) -> Chunk:
    blocks = [item.block for item in items]
    pages = [block.page_number for block in blocks if block.page_number is not None]
    line_starts = [item.line_start for item in items if item.line_start is not None]
    line_ends = [item.line_end for item in items if item.line_end is not None]
    section = _common_value(block.section for block in blocks)
    block_type = _common_value(block.type for block in blocks) or "mixed"
    table_ids = [block.table_id or block.block_id for block in blocks if block.type == "table"]
    chunk_id = f"{document.metadata.doc_id}_chunk_{index}"

    text_parts = _document_context(document, config)
    if config.add_section_headers and section:
        text_parts.append(f"Section: {section}")
    text_parts.extend(item.text for item in items)

    metadata = document.metadata
    chunk_metadata: dict[str, object] = {
        "chunk_id": chunk_id,
        "doc_id": metadata.doc_id,
        "ticker": metadata.ticker.lower(),
        "filing_type": metadata.filing_type or "",
        "period": metadata.period or "",
        "source_url": metadata.source_url or "",
        "title": metadata.title or "",
        "block_ids": ",".join(dict.fromkeys(block.block_id for block in blocks)),
        "block_type": block_type,
        "local_path": str(metadata.local_path) if metadata.local_path else "",
        "source": metadata.source or "local",
        "source_id": metadata.source_id or "",
        "source_created_at": metadata.source_created_at or "",
        "source_updated_at": metadata.source_updated_at or "",
        "fetched_at": metadata.fetched_at or "",
        "event_date": metadata.event_date or "",
        "content_sha256": metadata.content_sha256 or "",
        "company_id": metadata.company_id or "",
        "event_id": metadata.event_id or "",
        "source_type_id": metadata.source_type_id or "",
    }
    if pages:
        chunk_metadata.update(
            page_start=min(pages),
            page_end=max(pages),
            page_number=pages[0] if len(set(pages)) == 1 else 0,
        )
    if line_starts:
        chunk_metadata["line_start"] = min(line_starts)
    if line_ends:
        chunk_metadata["line_end"] = max(line_ends)
    if section:
        chunk_metadata["section"] = section
    if table_ids:
        chunk_metadata["table_id"] = ",".join(dict.fromkeys(table_ids))

    return Chunk(chunk_id=chunk_id, text="\n\n".join(text_parts), metadata=chunk_metadata)


def chunk_document(document: Document, config: ChunkingConfig | None = None) -> list[Chunk]:
    """Chunk a document without losing page, line, section, or table provenance."""

    config = config or ChunkingConfig()
    slices = [item for block in document.blocks for item in _slice_block(block, config)]
    groups = _group_slices(slices, config)
    return [_build_chunk(document, group, index, config) for index, group in enumerate(groups)]
