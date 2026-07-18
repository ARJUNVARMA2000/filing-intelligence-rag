from pathlib import Path

import pytest
import requests
from streamlit.testing.v1 import AppTest

from frontend.streamlit_app import ResearchServiceError, _post_json

APP_PATH = Path(__file__).parents[1] / "frontend" / "streamlit_app.py"


def test_research_workspace_landing_renders_without_exceptions() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=15)

    app.run()

    assert not app.exception
    assert len(app.chat_input) == 0
    assert any(
        field.placeholder == "Ask about revenue, margins, guidance, or risk…"
        for field in app.text_input
    )
    assert len(app.sidebar.text_input) == 2
    assert len(app.sidebar.slider) == 1
    assert any("Ask the filing" in block.value for block in app.markdown)
    assert any("Research service offline" in block.value for block in app.markdown)
    assert any("Revenue pulse" in button.label for button in app.button)


def test_conversation_and_evidence_states_render_without_exceptions() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=15)
    app.session_state["active_tickers"] = "AMZN"
    app.session_state["active_period"] = "Q3 2025"
    app.session_state["messages"] = [
        {"role": "user", "content": "What changed in the quarter?"},
        {
            "role": "assistant",
            "content": "Revenue increased, supported by the source evidence below.",
            "context_tickers": ["AMZN", "<unsafe>"],
            "context_period": "Q3 2025",
            "clarification_needed": True,
            "clarification_msg": "Confirm whether <script> should be in scope.",
            "citations": [
                {
                    "ticker": "AMZN",
                    "period": "Q3 2025",
                    "filing_type": "10-Q",
                    "doc_title": "Amazon <script> quarterly report",
                    "page": 12,
                    "line_start": 44,
                    "line_end": 51,
                    "relevance_score": 0.91,
                    "highlight_url": "/documents/amzn-highlight.pdf",
                    "text": "Representative source excerpt.",
                }
            ],
        },
    ]

    app.run()

    assert not app.exception
    assert len(app.chat_message) == 2
    assert len(app.chat_input) == 1
    assert any("Evidence ledger · 01 sources" in expander.label for expander in app.expander)
    rendered_markup = "\n".join(block.value for block in app.markdown)
    assert "&lt;unsafe&gt;" in rendered_markup
    assert "Amazon &lt;script&gt; quarterly report" in rendered_markup
    assert "Confirm whether &lt;script&gt; should be in scope." in rendered_markup


def test_api_transport_errors_are_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_request(*args, **kwargs):
        raise requests.ConnectionError("private backend hostname and provider details")

    monkeypatch.setattr(requests, "post", fail_request)

    with pytest.raises(ResearchServiceError) as exc_info:
        _post_json("/chat", {"question": "test"}, timeout=1)

    message = str(exc_info.value)
    assert "currently unavailable" in message
    assert "private backend" not in message
