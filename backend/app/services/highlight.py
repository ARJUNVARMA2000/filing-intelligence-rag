from __future__ import annotations

import re
from urllib.parse import quote

_SYNTHETIC_PREFIX_RE = re.compile(r"^(?:document|section):", re.IGNORECASE)


def source_text(text: str) -> str:
    """Remove retrieval-only context that does not appear in the source document."""

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    while paragraphs and _SYNTHETIC_PREFIX_RE.match(paragraphs[0]):
        paragraphs.pop(0)
    return "\n\n".join(paragraphs)


def build_search_phrase(text: str, max_words: int = 12) -> str:
    """
    Normalize whitespace and keep only the first N words to form a stable
    search phrase for PDF viewers.
    """
    normalized = " ".join(source_text(text).replace("|", " ").split())
    if not normalized:
        return ""
    words = normalized.split()
    return " ".join(words[:max_words])


def append_pdf_fragment(base: str, page: int | None, phrase: str) -> str:
    """
    Append page/search parameters to the base PDF URL, preserving any
    existing fragments.
    """
    fragment_parts = []
    if page:
        fragment_parts.append(f"page={page}")
    if phrase:
        fragment_parts.append(f"search={quote(phrase)}")
    if not fragment_parts:
        return base
    if "#" in base:
        return f"{base}&{'&'.join(fragment_parts)}"
    return f"{base}#{'&'.join(fragment_parts)}"
