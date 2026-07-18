import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from .models_registry import get_model_id

QuestionText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=6000),
]
HistoryText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]
_TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
_PERIOD_PATTERN = re.compile(r"^(?:(?:Q[1-4]|FY)-\d{4}|LATEST)$")


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(BaseModel):
    doc_id: str
    doc_title: str | None = None
    ticker: str | None = None
    filing_type: str | None = None
    period: str | None = None
    section: str | None = None
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    table_id: str | None = None
    source_url: str | None = None
    chunk_id: str | None = None
    highlight_url: str | None = None
    text: str | None = None  # Text preview for citation
    relevance_score: float | None = None  # Normalized similarity (higher is more relevant)


class UsageInfo(BaseModel):
    """Token usage and cost information for a request."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost: float = Field(default=0.0, ge=0)  # Cost in USD


class ChatMessage(RequestModel):
    """A bounded prior turn used only to resolve conversational references."""

    role: Literal["user", "assistant"]
    content: HistoryText


class ChatRequest(RequestModel):
    question: QuestionText
    tickers: list[str] | None = Field(default=None, max_length=8)
    period: str | None = None
    top_k: int = Field(default=8, ge=1, le=20)
    model: str | None = None  # OpenRouter model ID for evaluation
    history: list[ChatMessage] = Field(default_factory=list, max_length=8)

    @field_validator("tickers")
    @classmethod
    def normalize_tickers(cls, value: list[str] | None) -> list[str] | None:
        if not value:
            return None
        normalized: list[str] = []
        for ticker in value:
            candidate = ticker.strip().upper()
            if not _TICKER_PATTERN.fullmatch(candidate):
                raise ValueError(f"Invalid ticker symbol: {ticker!r}")
            if candidate not in normalized:
                normalized.append(candidate)
        return normalized or None

    @field_validator("period")
    @classmethod
    def normalize_period(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().upper().replace(" ", "-")
        if not _PERIOD_PATTERN.fullmatch(normalized):
            raise ValueError("period must use Q#-YYYY, FY-YYYY, or LATEST format")
        return normalized

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip()
        get_model_id(normalized)
        return normalized


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    raw_context: list[dict[str, Any]] | None = None
    model: str | None = None  # Model used for this response
    usage: UsageInfo | None = None  # Token usage and cost tracking
    retrieval_debug: dict[str, Any] | None = None  # Telemetry about retrieval (counts, thresholds)


class ParseQueryRequest(RequestModel):
    """Request to parse a user query for entity extraction."""

    question: QuestionText


class ParseQueryResponse(BaseModel):
    """Response containing extracted entities from a user query."""

    tickers: list[str] | None = None
    period: str | None = None
    needs_clarification: bool = False
    clarification_message: str | None = None
