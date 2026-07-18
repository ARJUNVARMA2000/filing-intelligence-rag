"""Deterministic query entity parsing with a validated LLM fallback."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from datetime import datetime

from ..dependencies import get_openai_client
from ..llm_client import ChatClient

COMPANY_ALIASES: dict[str, tuple[str, ...]] = {
    "AAPL": ("apple", "apple inc"),
    "ADS": ("adidas",),
    "AMZN": ("amazon", "amazon.com"),
    "COST": ("costco", "costco wholesale"),
    "IBM": ("ibm", "international business machines"),
    "JNJ": ("johnson & johnson", "johnson and johnson", "j&j"),
    "JPM": ("jpmorgan", "jp morgan", "jpmorgan chase"),
    "LOW": ("lowe's", "lowes", "lowe’s"),
    "META": ("meta", "meta platforms", "facebook"),
    "NFLX": ("netflix",),
    "NVDA": ("nvidia",),
    "TGT": ("target corporation", "target corp"),
    "TSLA": ("tesla",),
    "V": ("visa", "visa inc"),
    "WMT": ("walmart", "wal-mart"),
}

EXTRACTION_PROMPT = """You extract optional financial query filters.
Return only JSON with keys tickers, period, needs_clarification, clarification_message.
Tickers must be uppercase exchange symbols. Period must be Q#-YYYY, FY-YYYY, LATEST, or null.
Filters are optional: do not request clarification merely because ticker or period is absent.
Use LATEST only for 'latest' or 'most recent'; never reinterpret 'last quarter'.
Current date: CURRENT_DATE.
Example: {"tickers":["AMZN"],"period":"Q3-2025","needs_clarification":false,"clarification_message":null}
"""

_EXPLICIT_PERIOD_RE = re.compile(r"\bQ([1-4])\s*[-_/ ]?\s*((?:19|20)\d{2})\b", re.IGNORECASE)
_ANNUAL_PERIOD_RE = re.compile(
    r"\b(?:FY|fiscal\s+year|annual)\s*[-_/ ]?\s*((?:19|20)\d{2})\b", re.IGNORECASE
)
_ORDINAL_PERIOD_RE = re.compile(
    r"\b(first|second|third|fourth)\s+(?:fiscal\s+)?quarter(?:\s+of)?\s+((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_LATEST_RE = re.compile(r"\b(latest|most recent|last reported quarter)\b", re.IGNORECASE)
_PREVIOUS_RE = re.compile(r"\b(last quarter|previous quarter|prior quarter)\b", re.IGNORECASE)
_CURRENT_RE = re.compile(r"\b(current quarter|this quarter)\b", re.IGNORECASE)
_SYMBOL_RE = re.compile(r"(?<![A-Za-z0-9])\$?([A-Z][A-Z0-9.-]{0,9})(?![A-Za-z0-9])")
_SYMBOL_STOPWORDS = {
    "A",
    "AN",
    "AND",
    "ARE",
    "AS",
    "AT",
    "BY",
    "FOR",
    "FROM",
    "FY",
    "HOW",
    "I",
    "IN",
    "IS",
    "IT",
    "OF",
    "ON",
    "OR",
    "Q",
    "THE",
    "TO",
    "WAS",
    "WHAT",
    "WHEN",
    "WHERE",
    "WHICH",
    "WHO",
    "WHY",
    "WITH",
    "YOY",
}


def _calendar_quarter(value: datetime) -> tuple[int, int]:
    return value.year, ((value.month - 1) // 3) + 1


def _get_current_quarter(now: datetime | None = None) -> str:
    year, quarter = _calendar_quarter(now or datetime.now())
    return f"Q{quarter}-{year}"


def _get_previous_quarter(now: datetime | None = None) -> str:
    year, quarter = _calendar_quarter(now or datetime.now())
    if quarter == 1:
        return f"Q4-{year - 1}"
    return f"Q{quarter - 1}-{year}"


def _normalize_period(value: object, now: datetime) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper().replace("_", "-")
    explicit = _EXPLICIT_PERIOD_RE.fullmatch(text)
    if explicit:
        return f"Q{explicit.group(1)}-{explicit.group(2)}"
    annual = re.fullmatch(r"FY-?((?:19|20)\d{2})", text)
    if annual:
        return f"FY-{annual.group(1)}"
    if text in {"LATEST", "LATEST_AVAILABLE", "MOST_RECENT"}:
        return "LATEST"
    if text in {"PREVIOUS_QUARTER", "LAST_QUARTER"}:
        return _get_previous_quarter(now)
    if text == "CURRENT_QUARTER":
        return _get_current_quarter(now)
    return None


def _period_from_question(question: str, now: datetime) -> str | None:
    match = _EXPLICIT_PERIOD_RE.search(question)
    if match:
        return f"Q{match.group(1)}-{match.group(2)}"
    match = _ORDINAL_PERIOD_RE.search(question)
    if match:
        quarter = {"first": 1, "second": 2, "third": 3, "fourth": 4}[match.group(1).lower()]
        return f"Q{quarter}-{match.group(2)}"
    match = _ANNUAL_PERIOD_RE.search(question)
    if match:
        return f"FY-{match.group(1)}"
    if _PREVIOUS_RE.search(question):
        return _get_previous_quarter(now)
    if _CURRENT_RE.search(question):
        return _get_current_quarter(now)
    if _LATEST_RE.search(question):
        return "LATEST"
    return None


def _ticker_positions(question: str, catalog: dict[str, tuple[str, ...]]) -> list[tuple[int, str]]:
    positions: list[tuple[int, str]] = []
    alias_lookup = {
        alias.casefold(): ticker
        for ticker, aliases in catalog.items()
        for alias in (ticker, *aliases)
    }
    for ticker, aliases in catalog.items():
        for alias in (ticker, *aliases):
            match = re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", question, re.IGNORECASE)
            if match:
                positions.append((match.start(), ticker))
                break
    for match in _SYMBOL_RE.finditer(question):
        raw_symbol = match.group(1)
        symbol = alias_lookup.get(raw_symbol.casefold(), raw_symbol.upper())
        if symbol not in _SYMBOL_STOPWORDS and (
            not re.fullmatch(r"Q[1-4]|FY\d{4}", symbol)
            and (match.group(0).startswith("$") or match.group(1).isupper())
        ):
            positions.append((match.start(), symbol))
    positions.sort(key=lambda item: (item[0], item[1]))
    return positions


def _normalize_tickers(values: object, catalog: dict[str, tuple[str, ...]]) -> list[str] | None:
    if isinstance(values, str):
        raw_values: Iterable[object] = [values]
    elif isinstance(values, list):
        raw_values = values
    else:
        return None
    alias_lookup = {
        alias.casefold(): ticker
        for ticker, aliases in catalog.items()
        for alias in (ticker, *aliases)
    }
    result: list[str] = []
    for value in raw_values:
        text = str(value).strip()
        ticker = alias_lookup.get(text.casefold(), text.upper())
        if (
            re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker)
            and ticker not in _SYMBOL_STOPWORDS
            and ticker not in result
        ):
            result.append(ticker)
    return result or None


def _extract_json_block(text: str) -> str | None:
    fenced = re.search(r"```(?:json)?\s*({.*?})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group() if match else None


def _fallback_parse(question: str) -> tuple[list[str] | None, str | None]:
    now = datetime.now()
    tickers = list(
        dict.fromkeys(ticker for _, ticker in _ticker_positions(question, COMPANY_ALIASES))
    )
    return tickers or None, _period_from_question(question, now)


class QueryParser:
    def __init__(
        self,
        openai_client: ChatClient | None = None,
        *,
        ticker_catalog: dict[str, tuple[str, ...]] | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._openai = openai_client
        self._catalog = ticker_catalog or COMPANY_ALIASES
        self._now_factory = now_factory or datetime.now

    def parse(self, question: str) -> tuple[list[str] | None, str | None, bool, str | None]:
        normalized_question = " ".join(question.split())
        if not normalized_question:
            return None, None, True, "Please enter a financial research question."

        now = self._now_factory()
        tickers = (
            list(
                dict.fromkeys(
                    ticker for _, ticker in _ticker_positions(normalized_question, self._catalog)
                )
            )
            or None
        )
        period = _period_from_question(normalized_question, now)

        if tickers is not None and period is not None:
            return tickers, period, False, None
        if self._openai is None:
            return tickers, period, False, None

        try:
            prompt = EXTRACTION_PROMPT.replace("CURRENT_DATE", now.strftime("%B %d, %Y"))
            response = self._openai.chat(system_prompt=prompt, user_message=normalized_question)
            payload = json.loads(_extract_json_block(response) or response)
            llm_tickers = _normalize_tickers(payload.get("tickers"), self._catalog)
            llm_period = _normalize_period(payload.get("period"), now)
            tickers = tickers or llm_tickers
            period = period or llm_period
            needs_clarification = bool(payload.get("needs_clarification", False))
            clarification = payload.get("clarification_message")
            if not isinstance(clarification, str) or not clarification.strip():
                clarification = None
            return tickers, period, needs_clarification, clarification
        except (json.JSONDecodeError, TypeError, ValueError, RuntimeError, OSError):
            return tickers, period, False, None


def get_query_parser() -> QueryParser:
    return QueryParser(openai_client=get_openai_client())
