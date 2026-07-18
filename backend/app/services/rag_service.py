from __future__ import annotations

from functools import lru_cache

from ...ingestion.metadata_schema import Chunk
from ...vectorstore.chroma_store import ChromaVectorStore
from ..dependencies import get_app_settings, get_openai_client, get_openrouter_client
from ..llm_client import ChatClient
from ..models_registry import get_model_id
from ..openrouter_client import OpenRouterClient
from ..schemas import ChatRequest, ChatResponse, UsageInfo
from .citation import build_citations, select_cited_chunks
from .query_parser import QueryParser
from .ranking import rerank_candidates
from .retriever import Retriever

MIN_SIMILARITY = 0.35
MAX_TOP_K = 20

SYSTEM_PROMPT = """You are a precise financial analysis assistant.
Use only the supplied evidence. Every factual or numerical claim must end with one or more inline source IDs such as [S1] or [S1, S2].
Never invent a source ID. If the evidence does not answer the question, say so plainly.
State the company and fiscal period when ambiguity is possible, and preserve units, signs, and reported versus adjusted distinctions."""


def _generation_question(request: ChatRequest) -> str:
    if not request.history:
        return request.question
    prior_turns = "\n".join(
        f"{message.role.upper()}: {message.content}" for message in request.history
    )
    return (
        "Use the bounded conversation history only to resolve references in the current question. "
        "All financial facts must still come from the supplied evidence.\n\n"
        f"Conversation history:\n{prior_turns}\n\nCurrent question: {request.question}"
    )


def _format_context(chunks_with_scores: list[tuple[Chunk, float]]) -> str:
    parts: list[str] = []
    for index, (chunk, _distance) in enumerate(chunks_with_scores, start=1):
        metadata = chunk.metadata
        pages = ""
        page_start = metadata.get("page_start")
        page_end = metadata.get("page_end")
        if page_start:
            pages = f" | page {page_start}"
            if page_end and page_end != page_start:
                pages += f"-{page_end}"
        parts.append(
            f"[S{index}] {str(metadata.get('ticker') or '').upper()} | "
            f"{metadata.get('filing_type') or ''} | {metadata.get('period') or ''}{pages}\n{chunk.text}"
        )
    return "\n\n".join(parts)


class RAGService:
    def __init__(
        self,
        vector_store: ChromaVectorStore,
        openai_client: ChatClient | None = None,
        openrouter_client: OpenRouterClient | None = None,
        query_parser: QueryParser | None = None,
    ) -> None:
        self._vector_store = vector_store
        self._retriever = Retriever(vector_store)
        self._openai = openai_client or get_openai_client()
        self._openrouter = openrouter_client
        self._query_parser = query_parser or QueryParser()

    def get_available_periods(self, ticker: str) -> list[str]:
        return self._vector_store.get_available_periods(ticker)

    def get_all_available_data(self) -> dict[str, list[str]]:
        return self._vector_store.get_ticker_period_map()

    def _build_availability_message(
        self,
        requested_tickers: list[str] | None,
        requested_period: str | None,
    ) -> str:
        available = self.get_all_available_data()
        if not available:
            return "No financial documents are currently available in the index."
        if requested_tickers:
            requested = [ticker.upper() for ticker in requested_tickers]
            present = {ticker: available[ticker] for ticker in requested if ticker in available}
            if present:
                period_text = f" for {requested_period}" if requested_period else ""
                details = "; ".join(
                    f"{ticker}: {', '.join(periods)}" for ticker, periods in present.items()
                )
                return f"I could not find relevant evidence{period_text}. Available periods are {details}."
            return f"No indexed documents are available for {', '.join(requested)}."
        return "I could not find relevant evidence for that question. Add a company or fiscal period to narrow the search."

    def _retrieve(
        self,
        request: ChatRequest,
        top_k: int,
    ) -> tuple[list[tuple[Chunk, float]], dict[str, str]]:
        resolved: dict[str, str] = {}
        if request.period == "LATEST" and request.tickers:
            resolved = {
                ticker.upper(): period
                for ticker in request.tickers
                if (period := self._vector_store.get_latest_period(ticker))
            }
            combined: list[tuple[Chunk, float]] = []
            for ticker, period in resolved.items():
                combined.extend(
                    self._retriever.retrieve(
                        request.question,
                        k=top_k,
                        tickers=[ticker],
                        period=period,
                        min_similarity=MIN_SIMILARITY,
                    )
                )
            return rerank_candidates(request.question, combined, limit=top_k), resolved
        return (
            self._retriever.retrieve(
                request.question,
                k=top_k,
                tickers=request.tickers,
                period=request.period,
                min_similarity=MIN_SIMILARITY,
            ),
            resolved,
        )

    def answer(self, request: ChatRequest) -> ChatResponse:
        if not request.question.strip():
            return ChatResponse(
                answer="Please provide a financial question so I can search the filings and transcripts.",
                citations=[],
                raw_context=None,
                model=None,
                usage=None,
                retrieval_debug={"skipped": True, "reason": "empty_question"},
            )

        parsed_tickers: list[str] | None = None
        parsed_period: str | None = None
        if request.tickers is None or request.period is None:
            parsed_tickers, parsed_period, _, _ = self._query_parser.parse(request.question)
        scoped_request = request.model_copy(
            update={
                "tickers": request.tickers or parsed_tickers,
                "period": request.period or parsed_period,
            }
        )

        top_k = max(1, min(int(scoped_request.top_k), MAX_TOP_K))
        ranked, resolved_periods = self._retrieve(scoped_request, top_k)
        if not ranked:
            return ChatResponse(
                answer=self._build_availability_message(
                    scoped_request.tickers, scoped_request.period
                ),
                citations=[],
                raw_context=None,
                model=None,
                usage=None,
                retrieval_debug={
                    "requested_top_k": scoped_request.top_k,
                    "effective_top_k": top_k,
                    "filters": {
                        "tickers": scoped_request.tickers,
                        "period": scoped_request.period,
                        "resolved_periods": resolved_periods,
                    },
                    "retrieved": 0,
                },
            )

        system_prompt = f"{SYSTEM_PROMPT}\n\nEvidence:\n{_format_context(ranked)}"
        usage: UsageInfo | None = None
        model_used: str | None = None
        generation_question = _generation_question(scoped_request)
        if scoped_request.model:
            model_id = get_model_id(scoped_request.model)
            client = self._openrouter or get_openrouter_client(model_id)
            result = client.chat(
                system_prompt=system_prompt,
                user_message=generation_question,
                model=model_id,
            )
            answer_text = result.answer
            usage = UsageInfo(
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.total_tokens,
                cost=result.cost,
            )
            model_used = result.model
        else:
            answer_text = self._openai.chat(
                system_prompt=system_prompt,
                user_message=generation_question,
            )

        cited, citation_binding = select_cited_chunks(answer_text, ranked)
        return ChatResponse(
            answer=answer_text,
            citations=build_citations(cited, citation_binding["source_ids"]),
            raw_context=None,
            model=model_used,
            usage=usage,
            retrieval_debug={
                "requested_top_k": scoped_request.top_k,
                "effective_top_k": top_k,
                "filters": {
                    "tickers": scoped_request.tickers,
                    "period": scoped_request.period,
                    "resolved_periods": resolved_periods,
                },
                "retrieved": len(ranked),
                "min_similarity_threshold": MIN_SIMILARITY,
                "min_distance": min(score for _, score in ranked),
                "max_distance": max(score for _, score in ranked),
                "citation_binding": citation_binding,
            },
        )


@lru_cache
def get_rag_service() -> RAGService:
    settings = get_app_settings()
    store = ChromaVectorStore(persist_directory=str(settings.chroma_persist_dir))
    return RAGService(vector_store=store, openai_client=get_openai_client())
