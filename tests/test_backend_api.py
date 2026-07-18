from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.main import app
from backend.app.models_registry import EVAL_MODELS, get_model_id
from backend.app.routes import health as health_routes
from backend.app.schemas import ChatRequest, ChatResponse, ParseQueryRequest
from backend.app.security import require_frontend_identity
from backend.app.services.rag_service import get_rag_service


class _SuccessfulRAG:
    def answer(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(answer="$21.2B **reported**", citations=[])


class _FailingRAG:
    def answer(self, request: ChatRequest) -> ChatResponse:
        raise RuntimeError("private provider detail")


def _disable_route_auth() -> None:
    return None


@pytest.mark.parametrize("top_k", [0, -1, 21, 10_000])
def test_chat_request_rejects_out_of_range_top_k(top_k: int) -> None:
    with pytest.raises(ValidationError):
        ChatRequest(question="What was revenue?", top_k=top_k)


def test_chat_request_normalizes_filters_and_rejects_unknown_fields() -> None:
    request = ChatRequest(
        question="  What was revenue?  ",
        tickers=[" aapl ", "AAPL", "msft"],
        period="q3 2025",
    )

    assert request.question == "What was revenue?"
    assert request.tickers == ["AAPL", "MSFT"]
    assert request.period == "Q3-2025"
    with pytest.raises(ValidationError):
        ChatRequest(question="What was revenue?", debug=True)


@pytest.mark.parametrize("question", ["", "   ", "x" * 6001])
def test_question_contract_is_bounded(question: str) -> None:
    with pytest.raises(ValidationError):
        ParseQueryRequest(question=question)


def test_model_registry_accepts_only_configured_models() -> None:
    alias, model_id = next(iter(EVAL_MODELS.items()))
    assert get_model_id(alias) == model_id
    assert get_model_id(model_id) == model_id
    with pytest.raises(ValueError):
        get_model_id("attacker/unbudgeted-model")
    with pytest.raises(ValidationError):
        ChatRequest(question="What was revenue?", model="attacker/unbudgeted-model")


def test_chat_preserves_answer_text_and_sets_request_id() -> None:
    app.dependency_overrides[require_frontend_identity] = _disable_route_auth
    app.dependency_overrides[get_rag_service] = _SuccessfulRAG
    try:
        response = TestClient(app).post("/chat", json={"question": "What was revenue?"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["answer"] == "$21.2B **reported**"
    assert response.headers["X-Request-ID"]


def test_chat_failure_is_non_200_sanitized_and_traceable() -> None:
    app.dependency_overrides[require_frontend_identity] = _disable_route_auth
    app.dependency_overrides[get_rag_service] = _FailingRAG
    try:
        response = TestClient(app).post("/chat", json={"question": "What was revenue?"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert "private provider detail" not in response.text
    assert response.json()["detail"]["code"] == "internal_error"
    assert response.json()["detail"]["request_id"] == response.headers["X-Request-ID"]


def test_readiness_uses_collection_count_without_metadata_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Store:
        def count(self) -> int:
            return 42

        def get_stats(self) -> dict:
            raise AssertionError("readiness must not scan index metadata")

    monkeypatch.setattr(
        health_routes,
        "get_app_settings",
        lambda: SimpleNamespace(chroma_persist_dir="unused"),
    )
    monkeypatch.setattr(health_routes, "_get_health_store", lambda _: _Store())

    assert health_routes.readiness() == {"status": "ready", "index_chunks": 42}


def test_auth_is_fail_closed_without_google_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.app.security.get_app_settings",
        lambda: SimpleNamespace(
            auth_mode="google",
            app_env="production",
            frontend_service_account="",
            backend_audience="",
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        require_frontend_identity(None)

    assert exc_info.value.status_code == 503


def test_auth_bypass_is_rejected_outside_local_environments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.app.security.get_app_settings",
        lambda: SimpleNamespace(
            auth_mode="disabled",
            app_env="production",
            frontend_service_account="",
            backend_audience="",
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        require_frontend_identity(None)

    assert exc_info.value.status_code == 503
