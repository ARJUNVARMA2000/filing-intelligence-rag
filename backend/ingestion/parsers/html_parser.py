from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup, Tag

from ..metadata_schema import Block, Document, DocumentMetadata, Line, TableCell

_TEXT_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def _has_nested_content(element: Tag) -> bool:
    return any(
        isinstance(child, Tag) and child is not element and child.name in _TEXT_TAGS
        for child in element.descendants
    )


def _table_block(element: Tag, block_index: int, line_number: int) -> tuple[Block | None, int]:
    cells: list[TableCell] = []
    lines: list[Line] = []
    for row_index, row in enumerate(element.find_all("tr")):
        values: list[str] = []
        for column_index, cell in enumerate(row.find_all(["td", "th"], recursive=False)):
            text = _normalize_whitespace(cell.get_text(" ", strip=True))
            values.append(text)
            cells.append(TableCell(row=row_index, col=column_index, text=text))
        if any(values):
            rendered = " | ".join(values)
            lines.append(Line(line_number, rendered))
            line_number += 1
    if not lines:
        return None, line_number
    block_id = f"t_{block_index}"
    return (
        Block(
            block_id=block_id,
            type="table",
            page_number=None,
            text="\n".join(line.text for line in lines),
            lines=lines,
            cells=cells,
            table_id=block_id,
        ),
        line_number,
    )


def parse_html_to_document(
    file_path: Path,
    *,
    doc_id: str,
    ticker: str,
    filing_type: str,
    period: str,
    source_url: str | None = None,
    title: str | None = None,
) -> Document:
    soup = BeautifulSoup(file_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    for unwanted in soup.find_all(["script", "style", "noscript", "template"]):
        unwanted.decompose()

    blocks: list[Block] = []
    seen: set[tuple[str, str]] = set()
    current_section: str | None = None
    line_number = 1

    for element in soup.find_all([*_TEXT_TAGS, "table", "div"]):
        if not isinstance(element, Tag) or element.find_parent("table") is not None:
            continue
        if element.name == "table":
            block, line_number = _table_block(element, len(blocks), line_number)
            if block and ("table", block.text) not in seen:
                block.section = current_section
                blocks.append(block)
                seen.add(("table", block.text))
            continue
        if element.name == "div":
            if element.find(_TEXT_TAGS | {"table", "div"}, recursive=False) is not None:
                continue
        elif _has_nested_content(element):
            continue

        text = _normalize_whitespace(element.get_text(" ", strip=True))
        if not text or ("paragraph", text) in seen:
            continue
        if element.name in _HEADING_TAGS:
            current_section = text
        block = Block(
            block_id=f"p_{len(blocks)}",
            type="paragraph",
            page_number=None,
            text=text,
            lines=[Line(line_number, text)],
            section=current_section,
        )
        blocks.append(block)
        seen.add(("paragraph", text))
        line_number += 1

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
