from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.schemas import ChatRequest
from backend.app.services.citation import select_cited_chunks
from backend.app.services.query_parser import QueryParser
from backend.app.services.rag_service import RAGService, _generation_question
from backend.app.services.retriever import Retriever
from backend.ingestion.chunking import ChunkingConfig, chunk_document
from backend.ingestion.metadata_schema import Block, Chunk, Document, DocumentMetadata, Line
from backend.ingestion.parsers.html_parser import parse_html_to_document


def _document(blocks: list[Block]) -> Document:
    return Document(
        metadata=DocumentMetadata("doc", "AAPL", "10-Q", "Q2-2026", None, title="Results"),
        blocks=blocks,
    )


def test_chunking_preserves_line_section_and_table_provenance() -> None:
    paragraph = Block(
        "p1",
        "paragraph",
        2,
        "Revenue grew.\nMargins expanded.",
        [Line(10, "Revenue grew."), Line(11, "Margins expanded.")],
        section="management_discussion",
    )
    table = Block(
        "t1",
        "table",
        2,
        "Metric | Value\nRevenue | 10",
        [Line(12, "Metric | Value"), Line(13, "Revenue | 10")],
        section="management_discussion",
        table_id="t1",
    )
    chunks = chunk_document(
        _document([paragraph, table]),
        ChunkingConfig(max_tokens=20, max_block_tokens=10, overlap_tokens=0),
    )

    assert chunks[0].metadata["line_start"] == 10
    assert chunks[0].metadata["line_end"] == 11
    assert chunks[0].metadata["section"] == "management_discussion"
    assert chunks[1].metadata["table_id"] == "t1"
    assert "Metric | Value\nRevenue | 10" in chunks[1].text


def test_html_parser_avoids_nested_and_table_duplication(tmp_path: Path) -> None:
    path = tmp_path / "filing.html"
    path.write_text(
        "<div><p>Revenue grew 10%.</p><table><tr><th>Metric</th><th>Value</th></tr>"
        "<tr><td>Revenue</td><td>$10</td></tr></table></div><p>Outlook unchanged.</p>",
        encoding="utf-8",
    )
    document = parse_html_to_document(
        path, doc_id="d", ticker="AAPL", filing_type="10-Q", period="Q2-2026"
    )

    assert [block.type for block in document.blocks] == ["paragraph", "table", "paragraph"]
    assert [block.text for block in document.blocks] == [
        "Revenue grew 10%.",
        "Metric | Value\nRevenue | $10",
        "Outlook unchanged.",
    ]


def test_query_parser_previous_quarter_and_optional_filters() -> None:
    parser = QueryParser(now_factory=lambda: datetime(2026, 1, 15))

    assert parser.parse("How did Apple's revenue change last quarter?")[:2] == (["AAPL"], "Q4-2025")
    assert parser.parse("How did margins change?") == (None, None, False, None)


def test_retriever_fetches_wide_deduplicates_and_reranks() -> None:
    class Store:
        observed_k = 0

        def query(self, *, query_text, k, where):
            self.observed_k = k
            duplicate = Chunk("a", "Revenue grew", {"doc_id": "d", "chunk_id": "a"})
            return [
                (duplicate, 0.3),
                (duplicate, 0.1),
                (Chunk("b", "Unrelated", {"doc_id": "d", "chunk_id": "b"}), 0.2),
            ]

    store = Store()
    results = Retriever(store).retrieve("revenue growth", k=2)

    assert store.observed_k == 24
    assert [chunk.chunk_id for chunk, _ in results] == ["a", "b"]
    assert results[0][1] == 0.1


def test_citation_binding_uses_only_valid_inline_sources() -> None:
    chunks = [
        (Chunk("a", "A", {"doc_id": "d"}), 0.1),
        (Chunk("b", "B", {"doc_id": "d"}), 0.2),
        (Chunk("c", "C", {"doc_id": "d"}), 0.3),
    ]

    selected, debug = select_cited_chunks("Revenue grew [S2]. Margin improved [S1, S9].", chunks)

    assert [chunk.chunk_id for chunk, _ in selected] == ["b", "a"]
    assert debug["invalid_source_ids"] == ["S9"]


def test_citation_binding_never_pretends_uncited_evidence_was_used() -> None:
    chunks = [(Chunk("a", "A", {"doc_id": "d"}), 0.1)]

    selected, debug = select_cited_chunks("Revenue grew without a source marker.", chunks)

    assert selected == []
    assert debug["mode"] == "missing"


def test_chat_scope_supports_latest_and_bounded_conversation_history() -> None:
    request = ChatRequest(
        question="How did that compare?",
        period="latest",
        history=[
            {"role": "user", "content": "What was NVIDIA revenue?"},
            {"role": "assistant", "content": "Revenue was $10 [S1]."},
        ],
    )

    generation_question = _generation_question(request)

    assert request.period == "LATEST"
    assert "Conversation history:" in generation_question
    assert "Current question: How did that compare?" in generation_question
    with pytest.raises(ValidationError):
        ChatRequest(
            question="Too much history",
            history=[{"role": "user", "content": str(index)} for index in range(9)],
        )


def test_rag_orchestration_parses_scope_and_returns_only_answer_bound_evidence() -> None:
    class Store:
        where: dict | None = None

        def query(self, *, query_text, k, where):
            self.where = where
            return [
                (
                    Chunk(
                        "c1",
                        "Revenue was $10 million.",
                        {
                            "chunk_id": "c1",
                            "doc_id": "apple-q2",
                            "ticker": "aapl",
                            "period": "Q2-2026",
                            "filing_type": "10-Q",
                            "page_start": 3,
                            "line_start": 10,
                            "line_end": 11,
                        },
                    ),
                    0.1,
                )
            ]

    class ChatClient:
        def chat(self, system_prompt: str, user_message: str) -> str:
            assert "[S1]" in system_prompt
            return "Apple reported revenue of $10 million [S1]."

    store = Store()
    response = RAGService(
        store,
        openai_client=ChatClient(),
        query_parser=QueryParser(),
    ).answer(ChatRequest(question="What was Apple's revenue in Q2 2026?"))

    assert store.where == {"$and": [{"ticker": {"$in": ["aapl"]}}, {"period": "Q2-2026"}]}
    assert [citation.chunk_id for citation in response.citations] == ["c1"]
    assert response.raw_context is None
    assert response.retrieval_debug["citation_binding"]["mode"] == "answer_bound"
