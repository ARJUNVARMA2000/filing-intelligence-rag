from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..metadata_schema import Block, Document, DocumentMetadata, Line


def _paragraph_text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    text = value.get("text")
    return str(text).strip() if text is not None else ""


def parse_quartr_transcript_to_document(
    file_path: Path,
    *,
    doc_id: str,
    ticker: str,
    filing_type: str,
    period: str,
    source_url: str | None = None,
    title: str | None = None,
) -> Document:
    """Parse the documented Quartr transcript JSON format into paragraph blocks."""

    payload = json.loads(file_path.read_text(encoding="utf-8"))
    transcript = payload.get("transcript") if isinstance(payload, dict) else None
    if not isinstance(transcript, dict):
        raise ValueError(f"Quartr transcript is missing the transcript object: {file_path}")

    paragraphs = transcript.get("paragraphs")
    blocks: list[Block] = []
    if isinstance(paragraphs, list):
        for index, paragraph in enumerate(paragraphs, start=1):
            text = _paragraph_text(paragraph)
            if not text:
                continue
            speaker = paragraph.get("speaker") if isinstance(paragraph, dict) else None
            prefix = f"Speaker {speaker}: " if speaker is not None else ""
            rendered = prefix + text
            blocks.append(
                Block(
                    block_id=f"p_{index}",
                    type="paragraph",
                    page_number=None,
                    text=rendered,
                    lines=[Line(line_number=index, text=rendered)],
                )
            )

    if not blocks:
        text = str(transcript.get("text") or "").strip()
        if text:
            blocks.append(
                Block(
                    block_id="p_1",
                    type="paragraph",
                    page_number=None,
                    text=text,
                    lines=[Line(line_number=1, text=text)],
                )
            )
    if not blocks:
        raise ValueError(f"Quartr transcript contains no text: {file_path}")

    metadata = DocumentMetadata(
        doc_id=doc_id,
        ticker=ticker,
        filing_type=filing_type,
        period=period,
        source_url=source_url,
        title=title,
        local_path=file_path,
    )
    return Document(metadata=metadata, blocks=blocks)
