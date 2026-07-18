from __future__ import annotations

import re
from urllib.parse import quote

_SYNTHETIC_PREFIX_RE = re.compile(r"^(?:document|section):", re.IGNORECASE)
_SOURCE_BOUNDARY_RE = re.compile(r"[\n|\u2022\u25aa\u25cf]+")


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


def build_search_phrases(
    text: str,
    max_words: int = 12,
    fallback_words: int = 6,
    max_candidates: int = 10,
) -> list[str]:
    """Build ordered exact-match candidates for irregular PDF text layers."""

    source = source_text(text)
    if not source or max_words < 1 or max_candidates < 1:
        return []

    candidates: list[str] = []

    def add_candidate(value: str) -> None:
        words = " ".join(value.replace("|", " ").split()).split()
        if len(words) < 4:
            return
        for limit in (max_words, fallback_words):
            phrase = " ".join(words[:limit])
            if phrase and phrase not in candidates:
                candidates.append(phrase)

    # PDF text layers commonly reorder headings, chart labels, and table cells.
    # Search source lines/cells first, then retain the normalized whole passage.
    for segment in _SOURCE_BOUNDARY_RE.split(source):
        add_candidate(segment)
        if len(candidates) >= max_candidates:
            return candidates[:max_candidates]
    add_candidate(source)
    return candidates[:max_candidates]


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
