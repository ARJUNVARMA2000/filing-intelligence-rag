from __future__ import annotations

import html
import os
from urllib.parse import urljoin

import requests
import streamlit as st
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token

API_BASE = os.environ.get("FIN_RAG_API_BASE", "http://localhost:8000")
AUTH_MODE = os.environ.get("FIN_RAG_AUTH_MODE", "local")

SAMPLE_QUESTIONS = (
    (
        "Revenue pulse",
        "How much revenue did Amazon report in Q3 2025, and what drove the change?",
    ),
    (
        "Margin read-through",
        "Compare NVIDIA's gross margin commentary across Q2 and Q3 2026.",
    ),
    (
        "Management signals",
        "What risks did Walmart management emphasize in its latest earnings call?",
    ),
)


def _api_headers() -> dict[str, str]:
    if AUTH_MODE != "google":
        return {}
    token = id_token.fetch_id_token(GoogleAuthRequest(), API_BASE)
    return {"Authorization": f"Bearer {token}"}


class ResearchServiceError(RuntimeError):
    """A sanitized API error that is safe to display in the workspace."""


def _post_json(path: str, payload: dict, *, timeout: float) -> dict:
    """Call the research API without exposing transport or provider internals."""

    try:
        response = requests.post(
            f"{API_BASE}{path}",
            json=payload,
            headers=_api_headers(),
            timeout=timeout,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ResearchServiceError("The research service returned an invalid response.")
        return result
    except requests.Timeout as exc:
        raise ResearchServiceError(
            "The research service timed out. Try a narrower question or a smaller evidence depth."
        ) from exc
    except requests.ConnectionError as exc:
        raise ResearchServiceError(
            "The research service is currently unavailable. Check the backend connection and try again."
        ) from exc
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 500
        if status_code in {401, 403}:
            message = "This workspace is not authorized to use the research service."
        elif status_code == 422:
            message = "The research request is invalid. Review the ticker, period, and question."
        elif status_code == 429:
            message = "The research service is at capacity. Please try again shortly."
        else:
            message = "The research service could not complete this request. Please try again."
        raise ResearchServiceError(message) from exc
    except (requests.RequestException, ValueError) as exc:
        raise ResearchServiceError(
            "The research service returned an unreadable response. Please try again."
        ) from exc


@st.cache_data(ttl=30, show_spinner=False)
def _research_service_ready() -> bool:
    """Return the actual index readiness state without blocking the workspace."""

    try:
        response = requests.get(f"{API_BASE}/health/ready", timeout=2)
        if response.status_code != 200:
            return False
        payload = response.json()
        return payload.get("status") == "ready" and int(payload.get("index_chunks", 0)) > 0
    except (requests.RequestException, TypeError, ValueError):
        return False


def _resolve_url(path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    base = API_BASE.rstrip("/") + "/"
    return urljoin(base, path_or_url.lstrip("/"))


def _parse_query(question: str) -> dict:
    """Call the parse-query endpoint to extract entities from the question."""
    try:
        return _post_json("/chat/parse-query", {"question": question}, timeout=20)
    except ResearchServiceError:
        return {
            "tickers": None,
            "period": None,
            "needs_clarification": True,
            "clarification_message": (
                "Automatic scope detection is unavailable. "
                "Using the research parameters currently selected."
            ),
        }


def get_custom_css() -> str:
    return """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,500&display=swap');

        :root {
            --ink: #0a0d0c;
            --ink-soft: #111714;
            --panel: #151c18;
            --panel-raised: #1a231e;
            --line: rgba(233, 239, 227, 0.12);
            --line-strong: rgba(233, 239, 227, 0.22);
            --paper: #f2eee3;
            --paper-soft: #c7c8bf;
            --muted: #8d948c;
            --signal: #b8f36b;
            --signal-soft: rgba(184, 243, 107, 0.12);
            --amber: #dcb66d;
            --danger: #ef8f80;
            --serif: 'Newsreader', Georgia, serif;
            --sans: 'IBM Plex Sans', 'Segoe UI', sans-serif;
            --mono: 'IBM Plex Mono', 'Consolas', monospace;
        }

        html { scroll-behavior: smooth; }

        .stApp {
            color: var(--paper);
            background:
                radial-gradient(circle at 88% -10%, rgba(184, 243, 107, 0.09), transparent 28rem),
                radial-gradient(circle at 5% 55%, rgba(220, 182, 109, 0.05), transparent 32rem),
                var(--ink);
            font-family: var(--sans);
        }

        .stApp::before {
            content: '';
            position: fixed;
            inset: 0;
            pointer-events: none;
            opacity: 0.32;
            background-image:
                linear-gradient(rgba(255,255,255,0.018) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,0.018) 1px, transparent 1px);
            background-size: 44px 44px;
            mask-image: linear-gradient(to bottom, black, transparent 78%);
        }

        [data-testid='stHeader'] {
            background: transparent;
        }

        [data-testid='stAppViewContainer'] > .main .block-container {
            max-width: 1160px;
            padding: 2.25rem 3.25rem 8rem;
        }

        #MainMenu, footer, [data-testid='stDecoration'], [data-testid='stAppDeployButton'] { display: none; }

        h1, h2, h3, p, label, input, textarea, button {
            font-family: var(--sans);
        }

        a {
            color: var(--signal) !important;
            text-decoration-color: rgba(184, 243, 107, 0.35) !important;
            text-underline-offset: 3px;
        }

        ::selection { color: var(--ink); background: var(--signal); }
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #2a342e; border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: #3a473f; }

        /* Sidebar */
        [data-testid='stSidebar'] {
            background: rgba(13, 18, 16, 0.96);
            border-right: 1px solid var(--line);
        }

        [data-testid='stSidebar'] [data-testid='stSidebarContent'] {
            padding: 1.65rem 1.35rem 2rem;
        }

        .side-brand {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 0.2rem 0 1.85rem;
            border-bottom: 1px solid var(--line);
            margin-bottom: 1.65rem;
        }

        .brand-mark {
            position: relative;
            display: grid;
            place-items: center;
            width: 2.25rem;
            height: 2.25rem;
            color: var(--ink);
            background: var(--signal);
            font-family: var(--mono);
            font-size: 0.84rem;
            font-weight: 500;
            border-radius: 2px;
            box-shadow: 0 0 0 1px rgba(184,243,107,0.15), 0 0 32px rgba(184,243,107,0.08);
            overflow: hidden;
        }

        .brand-mark::after {
            content: '';
            position: absolute;
            inset: 0;
            background: linear-gradient(105deg, transparent 30%, rgba(255,255,255,0.55), transparent 70%);
            transform: translateX(-120%);
            animation: brand-sheen 4.8s ease-in-out infinite 1.2s;
        }

        .brand-name {
            color: var(--paper);
            font-family: var(--serif);
            font-size: 1.2rem;
            line-height: 1;
            letter-spacing: -0.02em;
        }

        .brand-edition {
            color: var(--muted);
            font-family: var(--mono);
            font-size: 0.58rem;
            letter-spacing: 0.13em;
            text-transform: uppercase;
            margin-top: 0.25rem;
        }

        .side-label, [data-testid='stSidebar'] label p {
            color: var(--muted) !important;
            font-family: var(--mono) !important;
            font-size: 0.64rem !important;
            font-weight: 500 !important;
            letter-spacing: 0.12em !important;
            text-transform: uppercase;
        }

        .side-section-title {
            color: var(--paper);
            font-size: 0.82rem;
            font-weight: 500;
            margin-bottom: 0.25rem;
        }

        .side-section-copy {
            color: var(--muted);
            font-size: 0.73rem;
            line-height: 1.55;
            margin-bottom: 1rem;
        }

        .coverage-card {
            position: relative;
            margin-top: 1.25rem;
            padding: 1rem;
            background: linear-gradient(135deg, rgba(184,243,107,0.08), rgba(184,243,107,0.015));
            border: 1px solid rgba(184,243,107,0.14);
            border-radius: 3px;
        }

        .coverage-card::before {
            content: '';
            position: absolute;
            top: -1px;
            left: 1rem;
            width: 2.5rem;
            height: 1px;
            background: var(--signal);
        }

        .coverage-status {
            display: flex;
            align-items: center;
            gap: 0.45rem;
            color: var(--signal);
            font-family: var(--mono);
            font-size: 0.62rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .coverage-dot {
            width: 5px;
            height: 5px;
            background: var(--signal);
            border-radius: 50%;
            box-shadow: 0 0 10px rgba(184,243,107,0.6);
            animation: pulse 2.2s ease-in-out infinite;
        }

        .coverage-card.offline { border-color: rgba(220, 182, 109, 0.22); }
        .coverage-card.offline .coverage-status { color: var(--amber); }
        .coverage-card.offline .coverage-dot {
            background: var(--amber);
            box-shadow: 0 0 10px rgba(220, 182, 109, 0.35);
            animation: none;
        }

        .coverage-card p {
            color: var(--muted);
            font-size: 0.7rem;
            line-height: 1.55;
            margin: 0.65rem 0 0;
        }

        /* Form controls */
        [data-baseweb='input'] {
            background: #0d1210 !important;
            border: 1px solid var(--line) !important;
            border-radius: 3px !important;
            transition: border-color 180ms ease, box-shadow 180ms ease;
        }

        [data-baseweb='input']:focus-within {
            border-color: rgba(184,243,107,0.65) !important;
            box-shadow: 0 0 0 3px rgba(184,243,107,0.08) !important;
        }

        [data-baseweb='input'] input {
            color: var(--paper) !important;
            font-family: var(--mono) !important;
            font-size: 0.78rem !important;
        }

        [data-baseweb='input'] input::placeholder { color: #596159 !important; }

        [data-testid='stSlider'] [role='slider'] {
            background: var(--signal);
            border-color: var(--signal);
            box-shadow: none;
        }

        [data-testid='stSlider'] [data-baseweb='slider'] > div > div {
            background: var(--signal);
        }

        [data-testid='stExpander'] {
            border: 1px solid var(--line);
            border-radius: 3px;
            background: rgba(255,255,255,0.015);
        }

        [data-testid='stExpander'] summary {
            color: var(--paper-soft);
            font-size: 0.75rem;
        }

        .stButton > button, .stLinkButton > a {
            min-height: 2.65rem;
            color: var(--paper) !important;
            background: var(--panel) !important;
            border: 1px solid var(--line-strong) !important;
            border-radius: 3px !important;
            font-family: var(--sans) !important;
            font-size: 0.78rem !important;
            font-weight: 500 !important;
            letter-spacing: 0.01em;
            box-shadow: none !important;
            transition: transform 180ms ease, border-color 180ms ease, background 180ms ease, color 180ms ease !important;
        }

        .stButton > button:hover, .stLinkButton > a:hover {
            color: var(--signal) !important;
            background: var(--panel-raised) !important;
            border-color: rgba(184,243,107,0.48) !important;
            transform: translateY(-2px);
        }

        .stButton > button:active, .stLinkButton > a:active { transform: translateY(0); }
        .stButton > button:focus-visible, .stLinkButton > a:focus-visible {
            outline: 2px solid var(--signal) !important;
            outline-offset: 2px;
        }

        [data-testid='stSidebar'] .stButton > button {
            color: var(--muted) !important;
            background: transparent !important;
            margin-top: 0.85rem;
        }

        /* Masthead */
        .app-masthead {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 0 1.1rem;
            border-bottom: 1px solid var(--line);
            margin-bottom: 4.2rem;
            animation: reveal 580ms cubic-bezier(.2,.75,.25,1) both;
        }

        .masthead-wordmark {
            display: flex;
            align-items: center;
            gap: 0.7rem;
        }

        .masthead-mark {
            color: var(--signal);
            font-family: var(--mono);
            font-size: 0.72rem;
        }

        .masthead-name {
            color: var(--paper);
            font-family: var(--serif);
            font-size: 1.08rem;
            letter-spacing: -0.02em;
        }

        .masthead-meta {
            display: flex;
            align-items: center;
            gap: 1rem;
            color: var(--muted);
            font-family: var(--mono);
            font-size: 0.6rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .live-indicator { color: var(--signal); }
        .live-indicator.offline { color: var(--amber); }

        /* Empty state */
        .hero-grid {
            display: grid;
            grid-template-columns: minmax(0, 1.65fr) minmax(270px, 0.65fr);
            gap: 5.5rem;
            align-items: end;
            margin-bottom: 4.5rem;
        }

        .hero-copy { animation: reveal 720ms cubic-bezier(.2,.75,.25,1) 100ms both; }

        .eyebrow {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            color: var(--signal);
            font-family: var(--mono);
            font-size: 0.65rem;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            margin-bottom: 1.7rem;
        }

        .eyebrow::before {
            content: '';
            width: 2.25rem;
            height: 1px;
            background: var(--signal);
        }

        .hero-title {
            max-width: 780px;
            color: var(--paper);
            font-family: var(--serif);
            font-size: clamp(3.7rem, 7.2vw, 6.4rem);
            font-weight: 400;
            line-height: 0.9;
            letter-spacing: -0.065em;
            margin: 0;
        }

        .stApp .hero-title {
            font-family: var(--serif) !important;
            font-weight: 400 !important;
        }

        .hero-title em {
            color: var(--signal);
            font-weight: 400;
        }

        .hero-subtitle {
            max-width: 660px;
            color: var(--paper-soft);
            font-size: 1rem;
            font-weight: 300;
            line-height: 1.7;
            margin: 2rem 0 0;
        }

        .protocol-card {
            position: relative;
            padding: 1.5rem 1.4rem;
            color: var(--ink);
            background: var(--paper);
            border-radius: 2px;
            box-shadow: 18px 22px 60px rgba(0,0,0,0.22);
            transform: rotate(1.2deg);
            animation: note-in 760ms cubic-bezier(.2,.75,.25,1) 260ms both;
        }

        .protocol-card::after {
            content: '';
            position: absolute;
            inset: 8px;
            border: 1px solid rgba(10,13,12,0.12);
            pointer-events: none;
        }

        .protocol-kicker {
            position: relative;
            z-index: 1;
            color: #5e655e;
            font-family: var(--mono);
            font-size: 0.57rem;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }

        .protocol-title {
            position: relative;
            z-index: 1;
            font-family: var(--serif);
            font-size: 1.45rem;
            line-height: 1.05;
            letter-spacing: -0.03em;
            margin: 0.7rem 0 1.3rem;
        }

        .protocol-row {
            position: relative;
            z-index: 1;
            display: grid;
            grid-template-columns: 1.6rem 1fr;
            gap: 0.55rem;
            align-items: baseline;
            padding: 0.62rem 0;
            border-top: 1px solid rgba(10,13,12,0.14);
            font-size: 0.72rem;
        }

        .protocol-row span:first-child {
            color: #7b837a;
            font-family: var(--mono);
            font-size: 0.58rem;
        }

        .trust-strip {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            border-top: 1px solid var(--line);
            border-bottom: 1px solid var(--line);
            margin-bottom: 3.5rem;
            animation: reveal 700ms ease 300ms both;
        }

        .trust-item { padding: 1.1rem 1.25rem 1rem 0; }
        .trust-item + .trust-item { border-left: 1px solid var(--line); padding-left: 1.25rem; }
        .trust-value { color: var(--paper); font-family: var(--serif); font-size: 1.15rem; }
        .trust-label {
            color: var(--muted);
            font-family: var(--mono);
            font-size: 0.56rem;
            letter-spacing: 0.09em;
            text-transform: uppercase;
            margin-top: 0.25rem;
        }

        .prompt-heading {
            display: flex;
            justify-content: space-between;
            align-items: end;
            margin-bottom: 0.9rem;
            animation: reveal 650ms ease 390ms both;
        }

        .prompt-heading h2 {
            color: var(--paper);
            font-family: var(--serif);
            font-size: 1.55rem;
            font-weight: 400;
            letter-spacing: -0.025em;
            margin: 0;
        }

        .prompt-heading span {
            color: var(--muted);
            font-family: var(--mono);
            font-size: 0.58rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .sample-grid-labels {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 0.75rem;
            margin-bottom: -0.45rem;
            pointer-events: none;
        }

        .sample-index {
            color: var(--muted);
            font-family: var(--mono);
            font-size: 0.56rem;
            letter-spacing: 0.08em;
            padding-left: 0.15rem;
        }

        [data-testid='stHorizontalBlock']:has(.sample-hook) { gap: 0.75rem; }
        .sample-hook { display: none; }

        [data-testid='stHorizontalBlock']:has(.sample-hook) .stButton > button {
            min-height: 7.6rem;
            justify-content: flex-start;
            align-items: flex-start;
            padding: 1.15rem 1.1rem;
            color: var(--paper) !important;
            background: linear-gradient(145deg, var(--panel), rgba(21,28,24,0.55)) !important;
            border-color: var(--line) !important;
            text-align: left;
            line-height: 1.45;
            animation: reveal 650ms ease both;
        }

        [data-testid='stHorizontalBlock']:has(.sample-hook) [data-testid='column']:nth-child(1) button { animation-delay: 430ms; }
        [data-testid='stHorizontalBlock']:has(.sample-hook) [data-testid='column']:nth-child(2) button { animation-delay: 510ms; }
        [data-testid='stHorizontalBlock']:has(.sample-hook) [data-testid='column']:nth-child(3) button { animation-delay: 590ms; }

        [data-testid='stHorizontalBlock']:has(.sample-hook) .stButton > button:hover {
            background: linear-gradient(145deg, #1b251f, #121914) !important;
        }

        .initial-query-heading {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            color: var(--muted);
            font-family: var(--mono);
            font-size: 0.58rem;
            letter-spacing: 0.09em;
            text-transform: uppercase;
            margin: 2.2rem 0 0.65rem;
        }

        .initial-query-heading::after {
            content: '';
            flex: 1;
            height: 1px;
            background: var(--line);
        }

        [data-testid='stForm'] {
            padding: 0 !important;
            background: transparent;
            border: 0 !important;
        }

        [data-testid='stForm'] [data-testid='stHorizontalBlock'] {
            gap: 0.65rem;
            align-items: end;
        }

        [data-testid='stForm'] [data-baseweb='input'] {
            min-height: 3.1rem;
            background: var(--panel) !important;
        }

        [data-testid='stForm'] [data-baseweb='input'] input {
            font-family: var(--sans) !important;
            font-size: 0.86rem !important;
        }

        [data-testid='stForm'] .stButton > button {
            min-height: 3.1rem;
            color: var(--ink) !important;
            background: var(--signal) !important;
            border-color: var(--signal) !important;
        }

        [data-testid='stForm'] .stButton > button:hover {
            color: var(--ink) !important;
            background: #c7ff7c !important;
        }

        /* Conversation */
        .conversation-header {
            display: flex;
            align-items: end;
            justify-content: space-between;
            margin-bottom: 2rem;
            animation: reveal 520ms ease both;
        }

        .conversation-header h1 {
            color: var(--paper);
            font-family: var(--serif);
            font-size: clamp(2.4rem, 5vw, 4.4rem);
            font-weight: 400;
            letter-spacing: -0.055em;
            line-height: 0.95;
            margin: 0;
        }

        .stApp .conversation-header h1 {
            font-family: var(--serif) !important;
            font-weight: 400 !important;
        }

        .conversation-context {
            color: var(--muted);
            font-family: var(--mono);
            font-size: 0.6rem;
            letter-spacing: 0.08em;
            text-align: right;
            text-transform: uppercase;
            line-height: 1.65;
        }

        [data-testid='stChatMessage'] {
            position: relative;
            max-width: 920px;
            margin: 0 0 1.15rem;
            padding: 1.45rem 1.6rem;
            background: rgba(20, 27, 23, 0.78);
            border: 1px solid var(--line);
            border-radius: 3px;
            animation: message-in 420ms cubic-bezier(.2,.75,.25,1) both;
        }

        [data-testid='stChatMessage']:has(.message-kicker.user) {
            max-width: 760px;
            margin-left: auto;
            background: var(--paper);
            border-color: var(--paper);
        }

        [data-testid='stChatMessage']:has(.message-kicker.user) p,
        [data-testid='stChatMessage']:has(.message-kicker.user) li {
            color: var(--ink) !important;
        }

        [data-testid='stChatMessageAvatarUser'],
        [data-testid='stChatMessageAvatarAssistant'] {
            background: transparent;
            border: 1px solid var(--line-strong);
            border-radius: 2px;
        }

        [data-testid='stChatMessage']:has(.message-kicker.user) [data-testid='stChatMessageAvatarUser'] {
            filter: invert(1);
        }

        [data-testid='stChatMessageContent'] {
            color: var(--paper-soft);
            font-family: var(--sans);
            font-size: 0.95rem;
            font-weight: 300;
            line-height: 1.72;
        }

        [data-testid='stChatMessageContent'] p:last-child { margin-bottom: 0; }
        [data-testid='stChatMessageContent'] strong { color: var(--paper); font-weight: 600; }
        [data-testid='stChatMessageContent'] h1,
        [data-testid='stChatMessageContent'] h2,
        [data-testid='stChatMessageContent'] h3 {
            color: var(--paper);
            font-family: var(--serif);
            font-weight: 400;
            letter-spacing: -0.025em;
        }

        .message-kicker {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            color: var(--signal);
            font-family: var(--mono);
            font-size: 0.58rem;
            font-weight: 500;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 0.85rem;
        }

        .message-kicker.user { color: #626a62; }
        .message-kicker::before { content: '◆'; font-size: 0.45rem; }

        .context-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin: -0.15rem 0 1rem;
        }

        .context-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.32rem 0.55rem;
            color: var(--signal);
            background: var(--signal-soft);
            border: 1px solid rgba(184,243,107,0.18);
            border-radius: 2px;
            font-family: var(--mono);
            font-size: 0.59rem;
            letter-spacing: 0.07em;
            text-transform: uppercase;
        }

        .context-chip::before { content: ''; width: 4px; height: 4px; background: currentColor; border-radius: 50%; }

        .clarification-card {
            display: grid;
            grid-template-columns: auto 1fr;
            gap: 0.8rem;
            align-items: start;
            padding: 0.9rem 1rem;
            color: #e8d4ac;
            background: rgba(220,182,109,0.08);
            border: 1px solid rgba(220,182,109,0.2);
            border-left: 2px solid var(--amber);
            border-radius: 2px;
            margin-bottom: 1rem;
        }

        .clarification-mark { color: var(--amber); font-family: var(--mono); font-size: 0.68rem; }
        .clarification-card strong {
            display: block;
            color: var(--amber) !important;
            font-family: var(--mono);
            font-size: 0.58rem;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            margin-bottom: 0.25rem;
        }

        .clarification-card span { color: #bcb19b; font-size: 0.75rem; line-height: 1.5; }

        /* Evidence drawer */
        [data-testid='stChatMessage'] [data-testid='stExpander'] {
            margin-top: 1.15rem;
            background: #101613;
        }

        [data-testid='stChatMessage'] [data-testid='stExpander'] summary:hover {
            color: var(--signal);
        }

        .source-card {
            display: grid;
            grid-template-columns: 2.25rem minmax(0, 1fr) auto;
            gap: 0.9rem;
            align-items: start;
            padding: 1rem 0 0.9rem;
            border-top: 1px solid var(--line);
        }

        .source-index {
            display: grid;
            place-items: center;
            width: 1.9rem;
            height: 1.9rem;
            color: var(--signal);
            border: 1px solid rgba(184,243,107,0.35);
            border-radius: 50%;
            font-family: var(--mono);
            font-size: 0.58rem;
        }

        .source-title {
            color: var(--paper);
            font-size: 0.82rem;
            font-weight: 500;
            line-height: 1.35;
        }

        .source-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem 0.7rem;
            color: var(--muted);
            font-family: var(--mono);
            font-size: 0.56rem;
            letter-spacing: 0.04em;
            margin-top: 0.4rem;
        }

        .source-score {
            min-width: 3.75rem;
            padding-top: 0.2rem;
            color: var(--muted);
            font-family: var(--mono);
            font-size: 0.55rem;
            text-align: right;
            text-transform: uppercase;
        }

        .source-score strong {
            display: block;
            color: var(--signal) !important;
            font-family: var(--serif);
            font-size: 1.05rem;
            font-weight: 400;
            margin-bottom: 0.05rem;
        }

        [data-testid='stChatMessage'] .stLinkButton > a {
            min-height: 2.35rem;
            font-family: var(--mono) !important;
            font-size: 0.62rem !important;
            text-transform: uppercase;
            letter-spacing: 0.07em;
        }

        [data-testid='stChatMessage'] [data-testid='stExpander'] pre {
            color: var(--paper-soft);
            background: #0b100e;
            border: 1px solid var(--line);
            border-radius: 2px;
            white-space: pre-wrap;
            font-family: var(--sans);
            font-size: 0.72rem;
            line-height: 1.55;
        }

        .source-divider { height: 0.3rem; }

        /* Processing state and chat composer */
        [data-testid='stStatusWidget'] {
            background: var(--panel) !important;
            border: 1px solid var(--line) !important;
            border-radius: 3px !important;
        }

        [data-testid='stBottom'] {
            background: linear-gradient(to top, var(--ink) 75%, transparent) !important;
        }

        [data-testid='stBottom'] > div {
            max-width: 1160px;
            margin: 0 auto;
            padding: 0 3.25rem 1rem;
        }

        [data-testid='stChatInput'] {
            background: rgba(18, 25, 21, 0.98) !important;
            border: 1px solid var(--line-strong) !important;
            border-radius: 3px !important;
            box-shadow: 0 18px 60px rgba(0,0,0,0.34) !important;
            transition: border-color 180ms ease, box-shadow 180ms ease;
        }

        [data-testid='stChatInput']:focus-within {
            border-color: rgba(184,243,107,0.55) !important;
            box-shadow: 0 0 0 3px rgba(184,243,107,0.07), 0 18px 60px rgba(0,0,0,0.34) !important;
        }

        [data-testid='stChatInput'] textarea {
            color: var(--paper) !important;
            font-family: var(--sans) !important;
            font-size: 0.9rem !important;
        }

        [data-testid='stChatInput'] textarea::placeholder { color: #717971 !important; }
        [data-testid='stChatInput'] button { color: var(--signal) !important; }

        [data-testid='stToast'] {
            color: var(--paper);
            background: var(--panel-raised);
            border: 1px solid var(--line-strong);
            border-radius: 3px;
        }

        @keyframes reveal {
            from { opacity: 0; transform: translateY(16px); }
            to { opacity: 1; transform: translateY(0); }
        }

        @keyframes note-in {
            from { opacity: 0; transform: translateY(22px) rotate(3deg); }
            to { opacity: 1; transform: translateY(0) rotate(1.2deg); }
        }

        @keyframes message-in {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        @keyframes pulse {
            0%, 100% { opacity: 0.45; transform: scale(0.85); }
            50% { opacity: 1; transform: scale(1.08); }
        }

        @keyframes brand-sheen {
            0%, 70%, 100% { transform: translateX(-120%); }
            82% { transform: translateX(120%); }
        }

        @media (max-width: 900px) {
            [data-testid='stAppViewContainer'] > .main .block-container {
                padding: 1.4rem 1.25rem 7.5rem;
            }

            [data-testid='stBottom'] > div { padding: 0 1.25rem 0.8rem; }
            .app-masthead { margin-bottom: 2.8rem; }
            .hero-grid { grid-template-columns: 1fr; gap: 2.5rem; }
            .protocol-card { max-width: 390px; transform: none; }
            .hero-title { font-size: clamp(3.3rem, 13vw, 5.2rem); }
            .trust-strip { margin-bottom: 2.6rem; }
            .conversation-header { align-items: start; flex-direction: column; gap: 1rem; }
            .conversation-context { text-align: left; }
            [data-testid='stChatMessage'] { max-width: 100%; }
        }

        @media (min-width: 901px) {
            [data-testid='stSidebar'],
            [data-testid='stSidebar'] > div:first-child {
                width: 310px !important;
            }
        }

        @media (max-width: 640px) {
            .masthead-meta span:not(.live-indicator) { display: none; }
            .masthead-meta .live-indicator { font-size: 0; }
            .masthead-meta .live-indicator::after { content: '●'; font-size: 0.62rem; }
            .eyebrow {
                align-items: flex-start;
                gap: 0.55rem;
                font-size: 0.58rem;
                line-height: 1.5;
                letter-spacing: 0.1em;
            }
            .eyebrow::before {
                flex: 0 0 1.75rem;
                width: 1.75rem;
                margin-top: 0.65em;
            }
            .hero-title {
                font-size: clamp(2.9rem, 13vw, 3.45rem);
                letter-spacing: -0.055em;
            }
            .hero-subtitle {
                padding-right: 0.25rem;
                font-size: 0.88rem;
                line-height: 1.65;
            }
            .protocol-card {
                width: 100%;
                max-width: 100%;
                box-sizing: border-box;
            }
            .trust-strip { grid-template-columns: 1fr; }
            .trust-item + .trust-item { border-left: 0; border-top: 1px solid var(--line); padding-left: 0; }
            .sample-grid-labels { display: none; }
            [data-testid='stHorizontalBlock']:has(.sample-hook) { flex-direction: column; }
            [data-testid='stHorizontalBlock']:has(.sample-hook) [data-testid='column'] { width: 100% !important; }
            [data-testid='stHorizontalBlock']:has(.sample-hook) .stButton > button { min-height: 5.7rem; }
            .prompt-heading span { display: none; }
            [data-testid='stChatMessage'] { padding: 1.1rem; }
            [data-testid='stChatMessage']:has(.message-kicker.user) { margin-left: 1.5rem; }
            .source-card { grid-template-columns: 2rem minmax(0, 1fr); }
            .source-score { display: none; }
        }

        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
                scroll-behavior: auto !important;
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
                transition-duration: 0.01ms !important;
            }
        }
    </style>
    """


def render_sidebar(service_ready: bool) -> int:
    with st.sidebar:
        st.markdown(
            """
            <div class="side-brand">
                <div class="brand-mark">FR</div>
                <div>
                    <div class="brand-name">FinRAG Research</div>
                    <div class="brand-edition">Analyst workspace / 01</div>
                </div>
            </div>
            <div class="side-section-title">Research parameters</div>
            <div class="side-section-copy">Optional filters narrow the document set before retrieval.</div>
            """,
            unsafe_allow_html=True,
        )

        tickers_input = st.text_input(
            "Ticker universe",
            value=st.session_state.active_tickers,
            key="input_tickers_widget",
            placeholder="AMZN, NVDA, JPM",
            help="Use comma-separated ticker symbols.",
        )
        period_input = st.text_input(
            "Reporting period",
            value=st.session_state.active_period,
            key="input_period_widget",
            placeholder="Q3 2025",
            help="Use a quarter, year, or reporting period.",
        )

        if tickers_input != st.session_state.active_tickers:
            st.session_state.active_tickers = tickers_input
        if period_input != st.session_state.active_period:
            st.session_state.active_period = period_input

        with st.expander("Retrieval controls"):
            top_k = st.slider(
                "Evidence depth",
                min_value=4,
                max_value=16,
                value=8,
                step=1,
                help="Number of source passages considered for each answer.",
            )

        if st.button("Start a new analysis", type="secondary", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

        service_label = "Research index ready" if service_ready else "Research service offline"
        st.markdown(
            f"""
            <div class="coverage-card{" offline" if not service_ready else ""}">
                <div class="coverage-status"><span class="coverage-dot"></span>{service_label}</div>
                <p>Answers are grounded in indexed filings, earnings materials, and transcripts. Every result keeps its source trail.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    return top_k


def render_masthead(service_ready: bool) -> None:
    service_label = "Index ready" if service_ready else "Service offline"
    st.markdown(
        f"""
        <header class="app-masthead">
            <div class="masthead-wordmark">
                <span class="masthead-mark">FR /</span>
                <span class="masthead-name">Financial Research</span>
            </div>
            <div class="masthead-meta">
                <span>Evidence-grounded intelligence</span>
                <span class="live-indicator{" offline" if not service_ready else ""}">● {service_label}</span>
            </div>
        </header>
        """,
        unsafe_allow_html=True,
    )


def render_empty_state(top_k: int) -> None:
    st.markdown(
        """
        <section class="hero-grid">
            <div class="hero-copy">
                <div class="eyebrow">Source-grounded financial analysis</div>
                <h1 class="hero-title">Ask the filing.<br><em>Get the evidence.</em></h1>
                <p class="hero-subtitle">
                    Move from a financial question to a defensible answer in seconds. FinRAG reads across
                    filings and earnings materials, then keeps every conclusion tied to its source.
                </p>
            </div>
            <aside class="protocol-card">
                <div class="protocol-kicker">Research protocol / 01</div>
                <div class="protocol-title">A clear trail from question to conclusion.</div>
                <div class="protocol-row"><span>01</span><div><strong>Define</strong> company and reporting period</div></div>
                <div class="protocol-row"><span>02</span><div><strong>Retrieve</strong> the strongest document evidence</div></div>
                <div class="protocol-row"><span>03</span><div><strong>Verify</strong> against page and line references</div></div>
            </aside>
        </section>
        <section class="trust-strip" aria-label="Research capabilities">
            <div class="trust-item"><div class="trust-value">Multi-company</div><div class="trust-label">Research coverage</div></div>
            <div class="trust-item"><div class="trust-value">Quarter-aware</div><div class="trust-label">Context detection</div></div>
            <div class="trust-item"><div class="trust-value">Line-level</div><div class="trust-label">Source verification</div></div>
        </section>
        <div class="prompt-heading">
            <h2>Begin with a research prompt</h2>
            <span>Or write your own below</span>
        </div>
        <div class="sample-grid-labels" aria-hidden="true">
            <div class="sample-index">01 / Revenue</div>
            <div class="sample-index">02 / Margins</div>
            <div class="sample-index">03 / Risk</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    columns = st.columns(3)
    for index, ((label, question), column) in enumerate(
        zip(SAMPLE_QUESTIONS, columns, strict=True)
    ):
        with column:
            st.markdown('<span class="sample-hook"></span>', unsafe_allow_html=True)
            if st.button(
                f"{label}\n\n{question}",
                key=f"sample_question_{index}",
                use_container_width=True,
            ):
                handle_question(question, top_k)
                st.rerun()

    st.markdown(
        '<div class="initial-query-heading">Start with your own question</div>',
        unsafe_allow_html=True,
    )
    with st.form("initial_research_query", clear_on_submit=True, border=False):
        query_column, submit_column = st.columns([5, 1])
        initial_query = query_column.text_input(
            "Research question",
            placeholder="Ask about revenue, margins, guidance, or risk…",
            label_visibility="collapsed",
        )
        submitted = submit_column.form_submit_button("Analyze →", use_container_width=True)
        if submitted and initial_query.strip():
            handle_question(initial_query.strip(), top_k)
            st.rerun()


def render_conversation_header() -> None:
    tickers = st.session_state.active_tickers.strip() or "Auto-detected universe"
    period = st.session_state.active_period.strip() or "Latest relevant period"
    answer_count = sum(1 for message in st.session_state.messages if message["role"] == "assistant")
    st.markdown(
        f"""
        <section class="conversation-header">
            <div>
                <div class="eyebrow">Active research thread</div>
                <h1>Analysis desk</h1>
            </div>
            <div class="conversation-context">
                {html.escape(tickers)}<br>
                {html.escape(period)} · {answer_count:02d} {"answer" if answer_count == 1 else "answers"}
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_context_chips(message: dict) -> None:
    tickers = message.get("context_tickers")
    period = message.get("context_period")
    if not tickers and not period:
        return

    chips = []
    if tickers:
        ticker_text = ", ".join(tickers) if isinstance(tickers, list) else str(tickers)
        chips.append(f'<span class="context-chip">{html.escape(ticker_text)}</span>')
    if period:
        chips.append(f'<span class="context-chip">{html.escape(str(period))}</span>')

    st.markdown(f'<div class="context-row">{"".join(chips)}</div>', unsafe_allow_html=True)


def render_citations(citations: list[dict]) -> None:
    with st.expander(f"Evidence ledger · {len(citations):02d} sources", expanded=False):
        for index, citation in enumerate(citations, start=1):
            page_number = citation.get("page")
            line_start = citation.get("line_start")
            line_end = citation.get("line_end")

            page_display = f"Page {page_number}" if page_number else "Page not listed"
            if line_start and line_end:
                line_display = f"Lines {line_start}–{line_end}"
            elif line_start:
                line_display = f"Line {line_start}"
            else:
                line_display = "Lines not listed"

            ticker = str(citation.get("ticker") or "Source").upper()
            period = str(citation.get("period") or "")
            filing_type = str(citation.get("filing_type") or "Document")
            document_title = str(citation.get("doc_title") or f"{ticker} {filing_type}")
            relevance_score = citation.get("relevance_score")

            score_html = ""
            if relevance_score is not None:
                relevance_percent = max(0, min(100, round(float(relevance_score) * 100)))
                score_html = (
                    f'<div class="source-score"><strong>{relevance_percent}%</strong>match</div>'
                )

            st.markdown(
                f"""
                <article class="source-card">
                    <div class="source-index">{index:02d}</div>
                    <div>
                        <div class="source-title">{html.escape(document_title)}</div>
                        <div class="source-meta">
                            <span>{html.escape(ticker)}</span>
                            {f"<span>{html.escape(period)}</span>" if period else ""}
                            <span>{html.escape(filing_type)}</span>
                            <span>{html.escape(page_display)}</span>
                            <span>{html.escape(line_display)}</span>
                        </div>
                    </div>
                    {score_html}
                </article>
                """,
                unsafe_allow_html=True,
            )

            action_columns = st.columns(2)
            highlight_url = citation.get("highlight_url")
            source_url = citation.get("source_url")
            citation_text = citation.get("text")

            if highlight_url:
                page_suffix = f" · p. {page_number}" if page_number else ""
                action_columns[0].link_button(
                    f"View cited page{page_suffix} ↗",
                    _resolve_url(str(highlight_url)),
                    help="Opens the evidence viewer in a new tab.",
                    use_container_width=True,
                )
            elif source_url:
                action_columns[0].link_button(
                    "Open source document ↗",
                    str(source_url),
                    use_container_width=True,
                )

            if citation_text:
                with action_columns[1].expander("Read source excerpt", expanded=False):
                    st.text(str(citation_text))

            st.markdown('<div class="source-divider"></div>', unsafe_allow_html=True)


def render_message(message: dict) -> None:
    role = message["role"]
    with st.chat_message(role):
        if role == "user":
            st.markdown(
                '<div class="message-kicker user">Research prompt</div>', unsafe_allow_html=True
            )
        else:
            st.markdown(
                '<div class="message-kicker assistant">FinRAG analysis</div>',
                unsafe_allow_html=True,
            )
            render_context_chips(message)

            if message.get("clarification_needed"):
                clarification = html.escape(
                    str(message.get("clarification_msg") or "More context may improve this answer.")
                )
                st.markdown(
                    f"""
                    <div class="clarification-card">
                        <div class="clarification-mark">!</div>
                        <div><strong>Scope note</strong><span>{clarification}</span></div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.write(message["content"])
        if role == "assistant" and message.get("citations"):
            render_citations(message["citations"])


def handle_question(question: str, top_k: int) -> None:
    """Process a question and add the grounded answer to the conversation."""
    st.session_state.messages.append({"role": "user", "content": question})
    status_placeholder = st.empty()

    with status_placeholder.status("Building the research brief…", expanded=True) as status:
        status.write("Identifying company and reporting period")
        parsed = _parse_query(question)
        new_tickers = parsed.get("tickers")
        new_period = parsed.get("period")

        if parsed.get("needs_clarification"):
            clarification_message = parsed.get(
                "clarification_message", "The company or reporting period could not be detected."
            )
            st.toast(f"Scope note: {clarification_message}", icon="ℹ️")
            status.write("Continuing with the available research scope")

        if new_tickers:
            ticker_string = ", ".join(new_tickers)
            st.session_state.active_tickers = ticker_string
        else:
            ticker_string = st.session_state.active_tickers

        if new_period:
            st.session_state.active_period = new_period
            period_string = new_period
        else:
            period_string = st.session_state.active_period

        ticker_list = [
            ticker.strip().upper() for ticker in ticker_string.split(",") if ticker.strip()
        ]
        history = [
            {
                "role": message["role"],
                "content": str(message.get("content") or "")[:2000],
            }
            for message in st.session_state.messages[:-1]
            if message.get("role") in {"user", "assistant"} and message.get("content")
        ][-8:]
        payload = {
            "question": question,
            "tickers": ticker_list or None,
            "period": period_string if period_string.strip() else None,
            "top_k": top_k,
            "history": history,
        }

        status.write("Retrieving and ranking source evidence")
        try:
            data = _post_json("/chat", payload, timeout=90)
            answer = str(data.get("answer") or "").strip()
            if not answer:
                raise ResearchServiceError("The research service returned an empty answer.")
            citations = data.get("citations", [])
            status.update(label="Research brief complete", state="complete", expanded=False)
        except ResearchServiceError as exc:
            status.update(label="Research request interrupted", state="error", expanded=True)
            answer = str(exc)
            citations = []

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
            "citations": citations,
            "context_tickers": new_tickers or ticker_list,
            "context_period": new_period or period_string,
            "clarification_needed": parsed.get("needs_clarification"),
            "clarification_msg": parsed.get("clarification_message"),
        }
    )
    status_placeholder.empty()


def main() -> None:
    st.set_page_config(
        page_title="FinRAG Research",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="auto",
    )
    st.markdown(get_custom_css(), unsafe_allow_html=True)

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "active_tickers" not in st.session_state:
        st.session_state.active_tickers = ""
    if "active_period" not in st.session_state:
        st.session_state.active_period = ""

    service_ready = _research_service_ready()
    top_k = render_sidebar(service_ready)
    render_masthead(service_ready)

    if st.session_state.messages:
        render_conversation_header()
        for message in st.session_state.messages:
            render_message(message)
    else:
        render_empty_state(top_k)

    if st.session_state.messages and (
        prompt := st.chat_input("Ask about revenue, margins, guidance, or risk…")
    ):
        handle_question(prompt, top_k)
        st.rerun()


if __name__ == "__main__":
    main()
