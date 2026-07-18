from __future__ import annotations

import re
from collections.abc import Iterable

from ..metadata_schema import Block

SECTION_PATTERNS = {
    "income_statement": re.compile(
        r"consolidated statements? of (?:operations|income|earnings)", re.I
    ),
    "balance_sheet": re.compile(r"consolidated balance sheets?", re.I),
    "cash_flow": re.compile(r"consolidated statements? of cash flows", re.I),
    "management_discussion": re.compile(r"management(?:'s)? discussion and analysis", re.I),
    "risk_factors": re.compile(r"\brisk factors?\b", re.I),
    "segment_information": re.compile(r"\bsegment (?:information|results|reporting)\b", re.I),
    "revenue": re.compile(r"\brevenues?\b|\bnet sales\b", re.I),
}


def clean_whitespace(text: str) -> str:
    return " ".join(text.split())


def _detect_section(text: str) -> str | None:
    for name, pattern in SECTION_PATTERNS.items():
        if pattern.search(text):
            return name
    return None


def tag_sections(blocks: Iterable[Block]) -> None:
    """Tag headings and carry their section forward through subsequent blocks."""

    current_section: str | None = None
    for block in blocks:
        detected = _detect_section(block.text)
        if detected:
            current_section = detected
        if not block.section:
            block.section = current_section
