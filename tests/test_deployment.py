import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routes.documents import (
    _get_vector_store,
    _json_for_script,
    _raw_relative_path,
    _resolve_local_path,
    get_document_file,
    view_document_chunk,
)
from backend.app.security import require_frontend_identity
from backend.app.services.highlight import build_search_phrase, build_search_phrases, source_text


def test_basic_health_endpoint() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("stored_path", "expected"),
    [
        (
            r"C:\Users\person\project\data\raw\NVDA\NVIDIA - Q3 2026.pdf",
            Path("nvda", "NVIDIA - Q3 2026.pdf"),
        ),
        (
            "data/raw/aapl/Apple - Q3 2025.pdf",
            Path("aapl", "Apple - Q3 2025.pdf"),
        ),
    ],
)
def test_legacy_document_paths_are_portable(stored_path: str, expected: Path) -> None:
    assert _raw_relative_path(stored_path) == expected


def test_document_path_rejects_parent_traversal() -> None:
    assert _raw_relative_path("data/raw/../private.txt") is None


def test_document_resolution_never_serves_an_absolute_path_outside_raw_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_raw = tmp_path / "configured" / "data" / "raw"
    configured_raw.mkdir(parents=True)
    poisoned = tmp_path / "poisoned" / "data" / "raw" / "aapl" / "secret.pdf"
    poisoned.parent.mkdir(parents=True)
    poisoned.write_bytes(b"private")
    monkeypatch.setattr(
        "backend.app.routes.documents.get_app_settings",
        lambda: SimpleNamespace(raw_dir=configured_raw),
    )

    assert _resolve_local_path(str(poisoned)) is None


def test_document_file_is_inline_and_exposes_range_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_dir = tmp_path / "data" / "raw"
    document_path = raw_dir / "nvda" / "earnings.pdf"
    document_path.parent.mkdir(parents=True)
    document_path.write_bytes(b"%PDF-1.4\n")
    chunk = SimpleNamespace(
        text="Revenue was $57.0 billion.",
        metadata={"doc_id": "doc-1", "local_path": str(document_path)},
    )
    store = SimpleNamespace(get_chunk=lambda _: chunk)
    monkeypatch.setattr(
        "backend.app.routes.documents.get_app_settings",
        lambda: SimpleNamespace(raw_dir=raw_dir, document_bucket=None),
    )

    response = get_document_file("doc-1", "chunk-1", store)

    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"] == 'inline; filename="earnings.pdf"'
    assert response.headers["access-control-allow-headers"] == "Range"
    assert "Content-Range" in response.headers["access-control-expose-headers"]
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(document_path.stat().st_size)


def test_local_document_file_serves_a_single_byte_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_dir = tmp_path / "data" / "raw"
    document_path = raw_dir / "nvda" / "earnings.pdf"
    document_path.parent.mkdir(parents=True)
    document_path.write_bytes(b"0123456789")
    chunk = SimpleNamespace(
        text="Revenue was $57.0 billion.",
        metadata={"doc_id": "doc-1", "local_path": str(document_path)},
    )
    monkeypatch.setattr(
        "backend.app.routes.documents.get_app_settings",
        lambda: SimpleNamespace(raw_dir=raw_dir, document_bucket=None),
    )
    app.dependency_overrides[_get_vector_store] = lambda: SimpleNamespace(get_chunk=lambda _: chunk)

    try:
        response = TestClient(app).get(
            "/documents/doc-1/chunks/chunk-1/file",
            headers={"Range": "bytes=2-5"},
        )
    finally:
        app.dependency_overrides.pop(_get_vector_store, None)

    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-length"] == "4"


def test_gcs_document_file_serves_a_suffix_byte_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"cloud-document"

    class FakeBlob:
        size = len(data)

        def reload(self) -> None:
            return None

        def open(self, mode: str):
            assert mode == "rb"
            return io.BytesIO(data)

    fake_blob = FakeBlob()
    fake_bucket = SimpleNamespace(blob=lambda _: fake_blob)
    fake_client = SimpleNamespace(bucket=lambda _: fake_bucket)
    raw_dir = tmp_path / "data" / "raw"
    chunk = SimpleNamespace(
        text="Revenue was $57.0 billion.",
        metadata={"doc_id": "doc-1", "local_path": "data/raw/nvda/earnings.pdf"},
    )
    monkeypatch.setattr("google.cloud.storage.Client", lambda: fake_client)
    monkeypatch.setattr(
        "backend.app.routes.documents.get_app_settings",
        lambda: SimpleNamespace(raw_dir=raw_dir, document_bucket="documents"),
    )
    app.dependency_overrides[_get_vector_store] = lambda: SimpleNamespace(get_chunk=lambda _: chunk)

    try:
        response = TestClient(app).get(
            "/documents/doc-1/chunks/chunk-1/file",
            headers={"Range": "bytes=-4"},
        )
    finally:
        app.dependency_overrides.pop(_get_vector_store, None)

    assert response.status_code == 206
    assert response.content == b"ment"
    assert response.headers["content-range"] == "bytes 10-13/14"
    assert response.headers["content-length"] == "4"


@pytest.mark.parametrize(
    "range_header",
    ["bytes=10-", "bytes=4-2", "bytes=-0", "bytes=0-1,4-5", "items=0-1"],
)
def test_document_file_rejects_unsatisfiable_or_unsupported_ranges(
    range_header: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_dir = tmp_path / "data" / "raw"
    document_path = raw_dir / "nvda" / "earnings.pdf"
    document_path.parent.mkdir(parents=True)
    document_path.write_bytes(b"0123456789")
    chunk = SimpleNamespace(
        text="Revenue was $57.0 billion.",
        metadata={"doc_id": "doc-1", "local_path": str(document_path)},
    )
    monkeypatch.setattr(
        "backend.app.routes.documents.get_app_settings",
        lambda: SimpleNamespace(raw_dir=raw_dir, document_bucket=None),
    )
    app.dependency_overrides[_get_vector_store] = lambda: SimpleNamespace(get_chunk=lambda _: chunk)

    try:
        response = TestClient(app).get(
            "/documents/doc-1/chunks/chunk-1/file",
            headers={"Range": range_header},
        )
    finally:
        app.dependency_overrides.pop(_get_vector_store, None)

    assert response.status_code == 416
    assert response.content == b""
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == "bytes */10"
    assert response.headers["content-length"] == "0"


def test_document_viewer_uses_consistent_pdfjs_assets_and_safe_fallback() -> None:
    chunk = SimpleNamespace(
        text='Document: context only\n\nRevenue </script><script>alert("x")</script> was $57B.',
        metadata={
            "doc_id": "doc/one",
            "local_path": "data/raw/nvda/earnings.pdf",
            "page_start": 3,
            "title": "NVIDIA <results>",
            "ticker": "nvda",
            "period": "Q3 2026",
            "filing_type": "Report",
        },
    )
    store = SimpleNamespace(get_chunk=lambda _: chunk)

    response = view_document_chunk("doc/one", "chunk?two", store)
    html = response.body.decode()

    assert "pdfjs-dist@4.2.67/web/pdf_viewer.css" in html
    assert 'const cdnBase = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.2.67"' in html
    assert "${cdnBase}/build/pdf.min.mjs" in html
    assert "${cdnBase}/web/pdf_viewer.mjs" in html
    assert "${cdnBase}/build/pdf.worker.min.mjs" in html
    assert "/build/pdf.min.js" not in html
    assert "/cmaps/" in html
    assert "/standard_fonts/" in html
    assert "/documents/doc%2Fone/chunks/chunk%3Ftwo/file#page=3" in html
    assert 'iframe title="Source PDF fallback"' in html
    assert 'iframe title="Source PDF fallback" src=' not in html
    assert 'eventBus.dispatch("find"' in html
    assert "window.setTimeout" not in html
    assert "event.rawQuery !== activeSearchPhrase()" in html
    assert 'pageNumber.addEventListener("input", navigateToRequestedPage)' in html
    assert 'pageNumber.addEventListener("change", navigateToRequestedPage)' in html
    assert 'pageNumber.addEventListener("keydown"' in html
    assert "linkService.goToPage(nextPage)" in html
    assert "position: absolute; inset: 0" in html
    assert "viewer," in html
    assert "--paper: #f3f0e8" in html
    assert "--cobalt: #2457d6" in html
    assert "--vermilion: #d55235" in html
    assert "<strong>Filing Intelligence</strong>" in html
    assert "Research, with receipts." in html
    assert 'class="document-name">NVIDIA &lt;results&gt;</p>' in html
    assert "NVIDIA &lt;results&gt;" in html
    assert "Document: context only" not in html
    assert "</script><script>alert" not in html
    assert "\\u003c/script\\u003e\\u003cscript\\u003e" in html


def test_highlight_phrase_removes_retrieval_only_context_and_table_separators() -> None:
    chunk_text = """Document: NVDA | Q3-2026 | Earnings release

Section: Financial highlights

Record revenue | was $57.0 billion, up 62% from a year ago."""

    assert source_text(chunk_text) == (
        "Record revenue | was $57.0 billion, up 62% from a year ago."
    )
    assert build_search_phrase(chunk_text) == (
        "Record revenue was $57.0 billion, up 62% from a year ago."
    )


def test_highlight_candidates_include_bullet_text_when_slide_order_is_irregular() -> None:
    chunk_text = """Document: NVDA | Q1-2026 | Investor deck

Data Center Highlights 73% Y/Y and | Recognized $4.6B in H20 revenue; also recognized a charge
\u2022 Blackwell represented nearly 70% of compute revenue in Q1."""

    candidates = build_search_phrases(chunk_text)

    assert candidates[0] == "Data Center Highlights 73% Y/Y and"
    assert "Recognized $4.6B in H20 revenue; also recognized a charge" in candidates
    assert "Blackwell represented nearly 70% of compute revenue in Q1." in candidates


def test_script_json_escapes_html_control_characters() -> None:
    assert _json_for_script("</script>&") == '"\\u003c/script\\u003e\\u0026"'


def test_identity_guard_allows_unconfigured_local_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.dependencies import get_app_settings

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.delenv("FRONTEND_SERVICE_ACCOUNT", raising=False)
    monkeypatch.delenv("BACKEND_AUDIENCE", raising=False)
    get_app_settings.cache_clear()
    try:
        require_frontend_identity(None)
    finally:
        get_app_settings.cache_clear()


def test_identity_guard_rejects_missing_token_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.dependencies import get_app_settings

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "google")
    monkeypatch.setenv(
        "FRONTEND_SERVICE_ACCOUNT", "finrag-frontend@example.iam.gserviceaccount.com"
    )
    monkeypatch.setenv("BACKEND_AUDIENCE", "https://backend.example.run.app")
    get_app_settings.cache_clear()
    try:
        with pytest.raises(HTTPException) as exc_info:
            require_frontend_identity(None)
        assert exc_info.value.status_code == 401
    finally:
        get_app_settings.cache_clear()


def test_cloudbuild_defaults_target_the_portfolio_services() -> None:
    project_root = Path(__file__).resolve().parents[1]
    standard = (project_root / "cloudbuild.yaml").read_text(encoding="utf-8")
    refresh = (project_root / "cloudbuild.refresh.yaml").read_text(encoding="utf-8")

    assert "_BACKEND_SERVICE: filing-intelligence-rag-api" in standard
    assert "_FRONTEND_SERVICE: filing-intelligence-rag" in standard
    assert "_BACKEND_SERVICE: filing-intelligence-rag-api" in refresh
    assert "https://filing-intelligence-rag-api-7pj7nolpla-uc.a.run.app" in standard
    assert "https://filing-intelligence-rag-7pj7nolpla-uc.a.run.app" in standard
    assert "https://filing-intelligence-rag-api-7pj7nolpla-uc.a.run.app" in refresh
    assert "https://filing-intelligence-rag-7pj7nolpla-uc.a.run.app" in refresh
    assert "\n      - finrag-backend\n" not in standard
    assert "\n      - finrag-frontend\n" not in standard
    assert "\n      - finrag-backend\n" not in refresh
    assert "https://finrag-backend-7pj7nolpla-uc.a.run.app" not in standard
    assert "https://finrag-frontend-7pj7nolpla-uc.a.run.app" not in standard
    assert "https://finrag-backend-7pj7nolpla-uc.a.run.app" not in refresh
    assert "https://finrag-frontend-7pj7nolpla-uc.a.run.app" not in refresh


def test_user_facing_docs_publish_only_the_portfolio_deployment() -> None:
    project_root = Path(__file__).resolve().parents[1]
    docs = {
        name: (project_root / name).read_text(encoding="utf-8")
        for name in ("README.md", "SETUP_GUIDE.md", "DATA_FRESHNESS.md")
    }

    for content in docs.values():
        assert "https://finrag-backend-7pj7nolpla-uc.a.run.app" not in content
        assert "https://finrag-frontend-7pj7nolpla-uc.a.run.app" not in content
        assert "https://finrag-research-api-7pj7nolpla-uc.a.run.app" not in content
        assert "https://finrag-research-7pj7nolpla-uc.a.run.app" not in content
        assert "https://sourcebound-finance-api-7pj7nolpla-uc.a.run.app" not in content
        assert "https://sourcebound-finance-7pj7nolpla-uc.a.run.app" not in content

    assert docs["README.md"].startswith("# Filing Intelligence RAG\n")
    assert "https://filing-intelligence-rag-7pj7nolpla-uc.a.run.app" in docs["README.md"]
    for content in docs.values():
        assert "https://filing-intelligence-rag-api-7pj7nolpla-uc.a.run.app" in content
