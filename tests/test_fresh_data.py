from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx

from backend.app.routes.health import _freshness
from backend.app.services.query_parser import QueryParser
from backend.ingestion import index_builder
from backend.ingestion.metadata_schema import Block, Document, DocumentMetadata, Line
from backend.ingestion.parsers.quartr_transcript_parser import (
    parse_quartr_transcript_to_document,
)
from backend.ingestion.sources.quartr_client import QuartrClient, QuartrResource
from backend.vectorstore.chroma_store import ChromaVectorStore
from scripts import build_index as build_index_script
from scripts.sync_quartr import sync_ticker_kind


def _resource(*, updated_at: str = "2026-07-17T12:00:00Z") -> QuartrResource:
    return QuartrResource(
        kind="transcripts",
        id=42,
        file_url="https://cdn.example/transcript.json",
        type_id=22,
        updated_at=updated_at,
        created_at="2026-07-17T10:00:00Z",
        company_id=7,
        event_id=9,
        event={
            "title": "Q2 2026 earnings call",
            "fiscalYear": 2026,
            "fiscalPeriod": "Q2",
            "date": "2026-07-17T09:00:00Z",
        },
    )


def test_quartr_client_uses_documented_cursor_and_filters() -> None:
    observed: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params)
        observed.append(query)
        cursor = int(query["cursor"])
        record = {
            "id": cursor + 1,
            "fileUrl": "https://cdn.example/file.pdf",
            "typeId": 7,
            "updatedAt": "2026-07-17T12:00:00Z",
            "createdAt": "2026-07-17T10:00:00Z",
            "companyId": 7,
            "eventId": 9,
            "event": {"fiscalYear": 2026, "fiscalPeriod": "Q2"},
        }
        return httpx.Response(
            200,
            json={
                "data": [record],
                "pagination": {"nextCursor": 100 if cursor == 0 else None},
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = QuartrClient("test-key", client=http_client)
    resources = list(
        client.iter_resources(
            "reports",
            tickers=["amzn", "AAPL"],
            updated_after="2026-07-01T00:00:00Z",
        )
    )

    assert [item.id for item in resources] == [1, 101]
    assert [item["cursor"] for item in observed] == ["0", "100"]
    assert observed[0]["tickers"] == "AAPL,AMZN"
    assert observed[0]["updatedAfter"] == "2026-07-01T00:00:00Z"
    assert observed[0]["expand"] == "event"


def test_quartr_client_does_not_forward_api_key_to_opaque_file_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "x-api-key" not in request.headers
        return httpx.Response(
            200,
            json={"transcript": {"text": "Prepared remarks", "paragraphs": []}},
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = QuartrClient("secret-key", client=http_client)

    content = client.download(_resource())

    assert b"Prepared remarks" in content


def test_quartr_sync_is_idempotent_and_advances_watermark_after_success(tmp_path: Path) -> None:
    transcript = json.dumps({"transcript": {"text": "Prepared remarks", "paragraphs": []}}).encode()

    class FakeClient:
        downloads = 0

        def iter_resources(self, *_args, **_kwargs):
            return iter([_resource()])

        def download(self, _item):
            self.downloads += 1
            return transcript

    state = {"version": 1, "watermarks": {}}
    client = FakeClient()
    first = sync_ticker_kind(
        client,
        ticker="AAPL",
        kind="transcripts",
        raw_root=tmp_path,
        state=state,
        lookback_days=30,
        overlap_minutes=5,
        full=False,
    )
    second = sync_ticker_kind(
        client,
        ticker="AAPL",
        kind="transcripts",
        raw_root=tmp_path,
        state=state,
        lookback_days=30,
        overlap_minutes=5,
        full=False,
    )

    assert first == {"seen": 1, "downloaded": 1, "unchanged": 0}
    assert second == {"seen": 1, "downloaded": 0, "unchanged": 1}
    assert client.downloads == 1
    assert state["watermarks"]["AAPL:transcripts"] == "2026-07-17T12:00:00Z"
    metadata_files = list(tmp_path.rglob("*.metadata.json"))
    assert len(metadata_files) == 1
    metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
    assert metadata["doc_id"] == "quartr_transcripts_9"
    assert metadata["period"] == "Q2-2026"
    assert metadata["source"] == "quartr"


def test_quartr_sync_prefers_edited_transcript_for_same_event(tmp_path: Path) -> None:
    raw = replace(_resource(), id=41, type_id=15, updated_at="2026-07-17T11:00:00Z")
    edited = replace(_resource(), id=42, type_id=22, updated_at="2026-07-17T12:00:00Z")

    class FakeClient:
        downloaded: list[int] = []

        def iter_resources(self, *_args, **_kwargs):
            return iter([raw, edited])

        def download(self, item):
            self.downloaded.append(item.id)
            return json.dumps({"transcript": {"text": "Edited text", "paragraphs": []}}).encode()

    state = {"version": 1, "watermarks": {}}
    client = FakeClient()
    sync_ticker_kind(
        client,
        ticker="AAPL",
        kind="transcripts",
        raw_root=tmp_path,
        state=state,
        lookback_days=30,
        overlap_minutes=5,
        full=False,
    )

    assert client.downloaded == [42]
    metadata_path = next(tmp_path.rglob("*.metadata.json"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["doc_id"] == "quartr_transcripts_9"
    assert metadata["source_id"] == "42"


def test_quartr_transcript_parser_preserves_paragraphs(tmp_path: Path) -> None:
    path = tmp_path / "transcript.json"
    path.write_text(
        json.dumps(
            {
                "transcript": {
                    "text": "Full text",
                    "paragraphs": [
                        {"speaker": 0, "text": "Revenue grew."},
                        {"speaker": 1, "text": "Margins expanded."},
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    document = parse_quartr_transcript_to_document(
        path,
        doc_id="quartr_transcripts_42",
        ticker="AAPL",
        filing_type="transcript",
        period="Q2-2026",
    )

    assert [block.text for block in document.blocks] == [
        "Speaker 0: Revenue grew.",
        "Speaker 1: Margins expanded.",
    ]


def test_build_index_loader_reads_quartr_transcript_sidecar(tmp_path: Path, monkeypatch) -> None:
    ticker_dir = tmp_path / "raw" / "aapl"
    ticker_dir.mkdir(parents=True)
    transcript_path = ticker_dir / "quartr_transcripts_9.json"
    transcript_path.write_text(
        json.dumps({"transcript": {"text": "Updated guidance.", "paragraphs": []}}),
        encoding="utf-8",
    )
    metadata_path = transcript_path.with_suffix(".json.metadata.json")
    metadata_path.write_text(
        json.dumps(
            {
                "source": "quartr",
                "resource_kind": "transcripts",
                "doc_id": "quartr_transcripts_9",
                "ticker": "AAPL",
                "period": "Q2-2026",
                "filing_type": "transcript",
                "source_id": "42",
                "source_url": "https://cdn.example/transcript.json",
                "fetched_at": "2026-07-17T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        build_index_script,
        "get_settings",
        lambda **_kwargs: SimpleNamespace(raw_dir=tmp_path / "raw"),
    )

    documents = build_index_script.load_documents_for_ticker("AAPL")

    assert len(documents) == 1
    assert documents[0].metadata.doc_id == "quartr_transcripts_9"
    assert documents[0].metadata.source == "quartr"
    assert documents[0].metadata.fetched_at == "2026-07-17T12:00:00Z"


def test_latest_period_uses_indexed_event_date_not_calendar_quarter() -> None:
    class FakeStore:
        _period_key = staticmethod(ChromaVectorStore._period_key)

        def get_all_metadata(self, **_kwargs):
            return [
                {"period": "Q4-2025", "event_date": "2026-02-01T00:00:00Z"},
                {"period": "Q1-2026", "event_date": "2026-05-01T00:00:00Z"},
            ]

    assert ChromaVectorStore.get_latest_period(FakeStore(), "AAPL") == "Q1-2026"


def test_query_parser_keeps_latest_symbolic_for_fiscal_resolution() -> None:
    class FakeChatClient:
        def chat(self, **_kwargs):
            return json.dumps(
                {
                    "tickers": ["AAPL"],
                    "period": "LATEST",
                    "needs_clarification": False,
                    "clarification_message": None,
                }
            )

    tickers, period, needs_clarification, _message = QueryParser(FakeChatClient()).parse(
        "What changed in Apple's latest quarter?"
    )

    assert tickers == ["AAPL"]
    assert period == "LATEST"
    assert needs_clarification is False


def test_freshness_reports_fresh_and_stale() -> None:
    now = datetime.now(UTC)
    fresh = _freshness({"latest_fetch": (now - timedelta(hours=2)).isoformat()}, 24)
    stale = _freshness({"latest_fetch": (now - timedelta(hours=48)).isoformat()}, 24)

    assert fresh["status"] == "fresh"
    assert stale["status"] == "stale"
    assert _freshness({}, 24)["status"] == "unknown"


def test_freshness_reports_partial_corpus_and_per_ticker_status() -> None:
    now = datetime.now(UTC)
    result = _freshness(
        {
            "latest_fetch": (now - timedelta(hours=2)).isoformat(),
            "ticker_latest_fetch": {
                "AAPL": (now - timedelta(hours=2)).isoformat(),
                "ADS": None,
                "NVDA": (now - timedelta(hours=48)).isoformat(),
            },
        },
        24,
    )

    assert result["status"] == "stale"
    assert result["fresh_tickers"] == ["AAPL"]
    assert result["stale_tickers"] == ["NVDA"]
    assert result["unknown_tickers"] == ["ADS"]
    assert result["by_ticker"]["AAPL"]["status"] == "fresh"
    assert result["by_ticker"]["ADS"]["status"] == "unknown"
    assert result["by_ticker"]["NVDA"]["status"] == "stale"


def test_freshness_does_not_treat_fresh_plus_unknown_as_fresh() -> None:
    now = datetime.now(UTC)
    result = _freshness(
        {
            "latest_fetch": (now - timedelta(hours=2)).isoformat(),
            "ticker_latest_fetch": {
                "AAPL": (now - timedelta(hours=2)).isoformat(),
                "ADS": None,
            },
        },
        24,
    )

    assert result["status"] == "partial"
    assert result["fresh_tickers"] == ["AAPL"]
    assert result["unknown_tickers"] == ["ADS"]


def test_store_stats_include_tickers_without_fetch_provenance() -> None:
    class FakeStore:
        def get_all_metadata(self, **_kwargs):
            return [
                {
                    "doc_id": "aapl-old",
                    "ticker": "aapl",
                    "period": "Q1-2025",
                    "source": "local",
                    "fetched_at": "",
                },
                {
                    "doc_id": "nvda-new",
                    "ticker": "nvda",
                    "period": "Q2-2026",
                    "source": "quartr",
                    "fetched_at": "2026-07-17T12:00:00Z",
                },
            ]

        def get_ticker_period_map(self):
            return {"AAPL": ["Q1-2025"], "NVDA": ["Q2-2026"]}

        def count(self):
            return 2

        embedding_contract = {"name": "test", "dimension": 1, "distance_metric": "cosine"}

    stats = ChromaVectorStore.get_stats(FakeStore())

    assert stats["ticker_latest_fetch"] == {
        "AAPL": None,
        "NVDA": "2026-07-17T12:00:00Z",
    }


def test_default_refresh_universe_covers_packaged_tickers() -> None:
    expected = "AAPL,ADS,AMZN,COST,IBM,JNJ,JPM,LOW,META,NFLX,NVDA,TGT,TSLA,V,WMT"
    project_root = Path(__file__).resolve().parents[1]

    assert f"DATA_TICKERS={expected}" in (project_root / ".env.example").read_text(encoding="utf-8")
    assert f"_TICKERS: {expected}" in (project_root / "cloudbuild.refresh.yaml").read_text(
        encoding="utf-8"
    )


def test_incremental_index_replaces_all_chunks_for_changed_document(
    tmp_path: Path, monkeypatch
) -> None:
    calls: dict[str, object] = {}

    class FakeCollection:
        def count(self):
            return 1

    class FakeStore:
        def __init__(self, **_kwargs):
            self._collection = FakeCollection()

        def delete_documents(self, doc_ids):
            calls["deleted"] = list(doc_ids)

        def reset(self):
            calls["reset"] = True

        def upsert(self, chunks):
            calls.setdefault("upserted", []).extend(chunks)

        def validate_embedding_contract(self):
            calls["validated"] = True

        def get_stats(self):
            return {"total_documents": 1, "total_chunks": 1}

    monkeypatch.setattr(index_builder, "ChromaVectorStore", FakeStore)
    document = Document(
        metadata=DocumentMetadata(
            doc_id="quartr_reports_42",
            ticker="AAPL",
            filing_type="report",
            period="Q2-2026",
            source_url="https://example.test/report.pdf",
        ),
        blocks=[
            Block(
                block_id="p_1",
                type="paragraph",
                page_number=1,
                text="Updated filing content.",
                lines=[Line(line_number=1, text="Updated filing content.")],
            )
        ],
    )

    index_builder.index_documents([document], persist_dir=tmp_path)

    assert calls["deleted"] == ["quartr_reports_42"]
    assert len(calls["upserted"]) == 1
