from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class Line:
    line_number: int
    text: str


BlockType = Literal["paragraph", "table", "chart"]


@dataclass(frozen=True)
class TableCell:
    row: int
    col: int
    text: str


@dataclass
class Block:
    block_id: str
    type: BlockType
    page_number: int | None
    text: str
    lines: list[Line] = field(default_factory=list)
    section: str | None = None
    cells: list[TableCell] | None = None
    table_id: str | None = None


@dataclass
class DocumentMetadata:
    doc_id: str
    ticker: str
    filing_type: str
    period: str
    source_url: str | None
    title: str | None = None
    local_path: Path | None = None
    source: str | None = None
    source_id: str | None = None
    source_created_at: str | None = None
    source_updated_at: str | None = None
    fetched_at: str | None = None
    event_date: str | None = None
    content_sha256: str | None = None
    company_id: str | None = None
    event_id: str | None = None
    source_type_id: str | None = None


@dataclass
class Document:
    metadata: DocumentMetadata
    blocks: list[Block]


@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
