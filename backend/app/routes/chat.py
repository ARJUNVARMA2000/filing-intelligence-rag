import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..llm_client import ProviderError
from ..schemas import ChatRequest, ChatResponse, ParseQueryRequest, ParseQueryResponse
from ..security import require_frontend_identity
from ..services.query_parser import QueryParser, get_query_parser
from ..services.rag_service import RAGService, get_rag_service

router = APIRouter(dependencies=[Depends(require_frontend_identity)])
logger = logging.getLogger(__name__)


def _raise_sanitized_error(exc: Exception, request_id: str) -> None:
    logger.exception(
        "Chat API request failed",
        extra={"request_id": request_id, "error_type": type(exc).__name__},
    )
    if isinstance(exc, ProviderError):
        status_code = status.HTTP_502_BAD_GATEWAY
        code = "provider_unavailable"
        message = "The language model provider is temporarily unavailable."
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        code = "internal_error"
        message = "The request could not be completed."
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "request_id": request_id},
        headers={"X-Request-ID": request_id},
    ) from exc


@router.post("", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    response: Response,
    rag_service: Annotated[RAGService, Depends(get_rag_service)],
) -> ChatResponse:
    request_id = str(uuid4())
    response.headers["X-Request-ID"] = request_id
    try:
        return rag_service.answer(request)
    except Exception as exc:
        _raise_sanitized_error(exc, request_id)


@router.post("/parse-query", response_model=ParseQueryResponse)
def parse_query(
    request: ParseQueryRequest,
    response: Response,
    query_parser: Annotated[QueryParser, Depends(get_query_parser)],
) -> ParseQueryResponse:
    """Parse a user query to extract ticker symbols and time periods."""
    request_id = str(uuid4())
    response.headers["X-Request-ID"] = request_id
    try:
        tickers, period, needs_clarification, clarification_message = query_parser.parse(
            request.question
        )
    except Exception as exc:
        _raise_sanitized_error(exc, request_id)
    return ParseQueryResponse(
        tickers=tickers,
        period=period,
        needs_clarification=needs_clarification,
        clarification_message=clarification_message,
    )
