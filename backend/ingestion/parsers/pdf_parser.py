from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

import pdfplumber

from ..metadata_schema import Block, Document, DocumentMetadata, Line, TableCell


@dataclass(frozen=True)
class _LocatedBlock:
    top: float
    kind: str
    text_lines: list[str]
    cells: list[TableCell] | None = None


def _inside_bbox(word: dict[str, Any], bbox: tuple[float, float, float, float]) -> bool:
    x = (float(word.get("x0", 0.0)) + float(word.get("x1", word.get("x0", 0.0)))) / 2
    y = (float(word.get("top", 0.0)) + float(word.get("bottom", word.get("top", 0.0)))) / 2
    x0, top, x1, bottom = bbox
    return x0 <= x <= x1 and top <= y <= bottom


def _find_tables(page: Any) -> list[Any]:
    try:
        return list(page.find_tables() or [])
    except (AttributeError, TypeError, ValueError):
        return []


def _table_blocks(
    page: Any, located_tables: list[Any]
) -> tuple[list[_LocatedBlock], list[tuple[float, float, float, float]]]:
    blocks: list[_LocatedBlock] = []
    bboxes: list[tuple[float, float, float, float]] = []

    if located_tables:
        table_values = [(table, table.extract()) for table in located_tables]
    else:
        table_values = [(None, table) for table in (page.extract_tables() or [])]

    for table_index, (table_object, rows) in enumerate(table_values):
        if not rows:
            continue
        cells: list[TableCell] = []
        text_lines: list[str] = []
        for row_index, row in enumerate(rows):
            rendered: list[str] = []
            for column_index, value in enumerate(row or []):
                text = " ".join(str(value or "").split())
                rendered.append(text)
                cells.append(TableCell(row=row_index, col=column_index, text=text))
            if any(rendered):
                text_lines.append(" | ".join(rendered))
        if not text_lines:
            continue
        bbox_value = getattr(table_object, "bbox", None)
        if bbox_value and len(bbox_value) == 4:
            bbox = tuple(float(value) for value in bbox_value)
            bboxes.append(bbox)
            top = bbox[1]
        else:
            top = float("inf") + table_index
        blocks.append(_LocatedBlock(top=top, kind="table", text_lines=text_lines, cells=cells))
    return blocks, bboxes


def _word_lines(
    page: Any, excluded_bboxes: list[tuple[float, float, float, float]]
) -> list[tuple[float, str]]:
    try:
        words = page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
    except (AttributeError, TypeError, ValueError):
        words = []
    valid_words = [
        word
        for word in words
        if isinstance(word, dict)
        and str(word.get("text") or "").strip()
        and not any(_inside_bbox(word, bbox) for bbox in excluded_bboxes)
    ]
    if not valid_words:
        text = page.extract_text() or ""
        if isinstance(text, list):
            text = " ".join(str(value) for value in text if value)
        return [
            (float(index), line.strip())
            for index, line in enumerate(str(text).splitlines())
            if line.strip()
        ]

    valid_words.sort(key=lambda item: (float(item.get("top", 0.0)), float(item.get("x0", 0.0))))
    lines: list[list[dict[str, Any]]] = []
    tops: list[float] = []
    for word in valid_words:
        top = float(word.get("top", 0.0))
        if not lines or abs(top - tops[-1]) > 3.0:
            lines.append([word])
            tops.append(top)
        else:
            lines[-1].append(word)
            tops[-1] = min(tops[-1], top)
    return [
        (
            top,
            " ".join(
                str(word.get("text") or "").strip()
                for word in sorted(line, key=lambda item: float(item.get("x0", 0.0)))
            ),
        )
        for top, line in zip(tops, lines, strict=True)
    ]


def _paragraph_blocks(
    page: Any, excluded_bboxes: list[tuple[float, float, float, float]]
) -> list[_LocatedBlock]:
    lines = _word_lines(page, excluded_bboxes)
    if not lines:
        return []
    positive_gaps = [
        right[0] - left[0]
        for left, right in zip(lines, lines[1:], strict=False)
        if right[0] > left[0]
    ]
    normal_gap = median(positive_gaps) if positive_gaps else 10.0
    paragraph_gap = max(10.0, normal_gap * 1.7)
    paragraphs: list[_LocatedBlock] = []
    current: list[str] = []
    current_top = lines[0][0]
    previous_top = lines[0][0]
    for top, text in lines:
        if current and top - previous_top > paragraph_gap:
            paragraphs.append(_LocatedBlock(current_top, "paragraph", current))
            current = []
            current_top = top
        current.append(text)
        previous_top = top
    if current:
        paragraphs.append(_LocatedBlock(current_top, "paragraph", current))
    return paragraphs


def _extract_page_blocks(page: Any, page_number: int) -> list[Block]:
    located_tables = _find_tables(page)
    tables, bboxes = _table_blocks(page, located_tables)
    located = _paragraph_blocks(page, bboxes) + tables
    located.sort(key=lambda item: (item.top, 0 if item.kind == "paragraph" else 1))

    blocks: list[Block] = []
    next_line = 1
    paragraph_index = 0
    table_index = 0
    for item in located:
        lines = [Line(next_line + offset, text) for offset, text in enumerate(item.text_lines)]
        next_line += len(lines)
        if item.kind == "table":
            block_id = f"t_{page_number}_{table_index}"
            table_index += 1
            blocks.append(
                Block(
                    block_id=block_id,
                    type="table",
                    page_number=page_number,
                    text="\n".join(item.text_lines),
                    lines=lines,
                    cells=item.cells,
                    table_id=block_id,
                )
            )
        else:
            block_id = f"p_{page_number}_{paragraph_index}"
            paragraph_index += 1
            blocks.append(
                Block(
                    block_id=block_id,
                    type="paragraph",
                    page_number=page_number,
                    text="\n".join(item.text_lines),
                    lines=lines,
                )
            )
    return blocks


def _extract_paragraph_blocks(page: Any, starting_block_id: int, page_number: int) -> list[Block]:
    del starting_block_id
    return [block for block in _extract_page_blocks(page, page_number) if block.type == "paragraph"]


def _extract_table_blocks(page: Any, starting_block_id: int, page_number: int) -> list[Block]:
    del starting_block_id
    return [block for block in _extract_page_blocks(page, page_number) if block.type == "table"]


def parse_pdf_to_document(
    file_path: Path,
    *,
    doc_id: str,
    ticker: str,
    filing_type: str,
    period: str,
    source_url: str | None = None,
    title: str | None = None,
) -> Document:
    blocks: list[Block] = []
    with pdfplumber.open(file_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            blocks.extend(_extract_page_blocks(page, page_number))
    return Document(
        metadata=DocumentMetadata(
            doc_id=doc_id,
            ticker=ticker,
            filing_type=filing_type,
            period=period,
            source_url=source_url,
            title=title,
            local_path=file_path,
        ),
        blocks=blocks,
    )
