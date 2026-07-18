from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from ...vectorstore.chroma_store import ChromaVectorStore
from ..dependencies import get_app_settings
from ..services.highlight import build_search_phrase, build_search_phrases, source_text

router = APIRouter()

_STREAM_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class _DocumentSource:
    filename: str
    size: int
    stream_range: Callable[[int, int], Iterator[bytes]]


@lru_cache
def _get_vector_store() -> ChromaVectorStore:
    settings = get_app_settings()
    return ChromaVectorStore(persist_directory=str(settings.chroma_persist_dir))


def _load_chunk(doc_id: str, chunk_id: str, store: ChromaVectorStore):
    chunk = store.get_chunk(chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Chunk not found.")
    chunk_doc_id = str(chunk.metadata.get("doc_id") or "")
    if chunk_doc_id != doc_id:
        raise HTTPException(
            status_code=404, detail="Chunk does not belong to the requested document."
        )
    return chunk


def _raw_relative_path(path_value: str) -> Path | None:
    """Convert legacy Windows index paths into a portable data/raw path."""

    parts = [part for part in path_value.replace("\\", "/").split("/") if part]
    lowered = [part.lower() for part in parts]
    for index in range(len(parts) - 1):
        if lowered[index : index + 2] == ["data", "raw"]:
            relative_parts = parts[index + 2 :]
            if relative_parts and all(part not in {".", ".."} for part in relative_parts):
                relative_parts[0] = relative_parts[0].lower()
                return Path(*relative_parts)
    return None


def _resolve_local_path(path_value: str) -> Path | None:
    """Resolve an indexed path only when it remains inside the configured raw root."""

    relative = _raw_relative_path(path_value)
    if relative is None:
        return None
    raw_root = get_app_settings().raw_dir.resolve()
    portable_path = (raw_root / relative).resolve()
    if not portable_path.is_relative_to(raw_root):
        return None
    return portable_path if portable_path.is_file() else None


def _stream_local_range(path: Path, start: int, length: int) -> Iterator[bytes]:
    remaining = length
    with path.open("rb") as source:
        source.seek(start)
        while remaining:
            content = source.read(min(_STREAM_CHUNK_SIZE, remaining))
            if not content:
                break
            remaining -= len(content)
            yield content


def _load_document_from_bucket(path_value: str) -> _DocumentSource | None:
    settings = get_app_settings()
    if not settings.document_bucket:
        return None

    relative = _raw_relative_path(path_value)
    if relative is None:
        return None

    from google.api_core.exceptions import NotFound
    from google.cloud import storage

    object_name = "/".join(("raw", *relative.parts))
    blob = storage.Client().bucket(settings.document_bucket).blob(object_name)
    try:
        blob.reload()
    except NotFound:
        return None

    def stream_range(start: int, length: int) -> Iterator[bytes]:
        remaining = length
        with blob.open("rb") as source:
            source.seek(start)
            while remaining:
                content = source.read(min(_STREAM_CHUNK_SIZE, remaining))
                if not content:
                    break
                remaining -= len(content)
                yield content

    return _DocumentSource(
        filename=relative.name,
        size=int(blob.size or 0),
        stream_range=stream_range,
    )


def _parse_byte_range(range_header: str, size: int) -> tuple[int, int]:
    """Return an inclusive single byte range or reject malformed/unsatisfiable input."""

    unit, separator, value = range_header.strip().partition("=")
    if separator != "=" or unit.strip().lower() != "bytes" or not value or "," in value:
        raise ValueError("Only one byte range is supported.")

    start_value, dash, end_value = value.strip().partition("-")
    if dash != "-" or (not start_value and not end_value) or size <= 0:
        raise ValueError("Invalid byte range.")
    if (start_value and not start_value.isdigit()) or (end_value and not end_value.isdigit()):
        raise ValueError("Invalid byte range.")

    try:
        if not start_value:
            suffix_length = int(end_value)
            if suffix_length <= 0:
                raise ValueError("Invalid suffix byte range.")
            start = max(size - suffix_length, 0)
            end = size - 1
        else:
            start = int(start_value)
            end = size - 1 if not end_value else min(int(end_value), size - 1)
    except ValueError as exc:
        raise ValueError("Invalid byte range.") from exc

    if start < 0 or start >= size or end < start:
        raise ValueError("Unsatisfiable byte range.")
    return start, end


def _format_snippet(text: str, phrase: str) -> str:
    snippet = text.strip()
    if not snippet:
        return ""
    if not phrase:
        return escape(snippet)
    lowered = snippet.lower()
    lowered_phrase = phrase.lower()
    index = lowered.find(lowered_phrase)
    if index == -1:
        return escape(snippet)
    before = escape(snippet[:index])
    match = escape(snippet[index : index + len(phrase)])
    after = escape(snippet[index + len(phrase) :])
    return f"{before}<mark>{match}</mark>{after}"


def _positive_page(value: object) -> int:
    try:
        page = int(value)
    except (TypeError, ValueError):
        return 1
    return page if page > 0 else 1


def _document_endpoint(doc_id: str, chunk_id: str, endpoint: str) -> str:
    safe_doc_id = quote(doc_id, safe="")
    safe_chunk_id = quote(chunk_id, safe="")
    return f"/documents/{safe_doc_id}/chunks/{safe_chunk_id}/{endpoint}"


def _json_for_script(value: object) -> str:
    return json.dumps(value).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


@router.get("/documents/{doc_id}/chunks/{chunk_id}/file")
def get_document_file(
    doc_id: str,
    chunk_id: str,
    store: Annotated[ChromaVectorStore, Depends(_get_vector_store)],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    chunk = _load_chunk(doc_id, chunk_id, store)
    local_path_value = str(chunk.metadata.get("local_path") or "")
    if not local_path_value:
        raise HTTPException(
            status_code=404, detail="Local file path is not available for this chunk."
        )
    file_path = _resolve_local_path(local_path_value)
    cloud_document = None if file_path else _load_document_from_bucket(local_path_value)
    if file_path is None and cloud_document is None:
        raise HTTPException(
            status_code=404, detail="Document file not found on server or in document storage."
        )

    if file_path:
        source = _DocumentSource(
            filename=file_path.name,
            size=file_path.stat().st_size,
            stream_range=lambda start, length: _stream_local_range(file_path, start, length),
        )
    else:
        source = cloud_document

    filename = source.filename
    safe_filename = filename.replace('"', "")
    suffix = Path(filename).suffix.lower()
    media_type = "text/html" if suffix == ".html" else "application/pdf"
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Range",
        "Access-Control-Expose-Headers": "Accept-Ranges, Content-Length, Content-Range",
        "Content-Disposition": f'inline; filename="{safe_filename}"',
        "Cache-Control": "public, max-age=3600",
        "Accept-Ranges": "bytes",
    }

    if range_header:
        try:
            start, end = _parse_byte_range(range_header, source.size)
        except ValueError:
            return Response(
                status_code=416,
                headers={
                    **headers,
                    "Content-Range": f"bytes */{source.size}",
                    "Content-Length": "0",
                },
            )
        length = end - start + 1
        return StreamingResponse(
            source.stream_range(start, length),
            status_code=206,
            media_type=media_type,
            headers={
                **headers,
                "Content-Range": f"bytes {start}-{end}/{source.size}",
                "Content-Length": str(length),
            },
        )

    return StreamingResponse(
        source.stream_range(0, source.size),
        media_type=media_type,
        headers={**headers, "Content-Length": str(source.size)},
    )


@router.get(
    "/documents/{doc_id}/chunks/{chunk_id}/viewer",
    response_class=HTMLResponse,
)
def view_document_chunk(
    doc_id: str,
    chunk_id: str,
    store: Annotated[ChromaVectorStore, Depends(_get_vector_store)],
) -> HTMLResponse:
    chunk = _load_chunk(doc_id, chunk_id, store)
    local_path_value = str(chunk.metadata.get("local_path") or "")
    if not local_path_value:
        raise HTTPException(
            status_code=404, detail="Local file path is not available for this chunk."
        )

    page = _positive_page(chunk.metadata.get("page_start"))
    phrase = build_search_phrase(chunk.text)
    search_phrases = build_search_phrases(chunk.text)
    pdf_src = _document_endpoint(doc_id, chunk_id, "file")
    native_pdf_src = f"{pdf_src}#page={page}"
    snippet_html = _format_snippet(source_text(chunk.text), phrase)

    pdf_url_js = _json_for_script(pdf_src)
    search_phrases_js = _json_for_script(search_phrases)
    page_js = _json_for_script(page)
    cdn_base = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.2.67"

    doc_title = escape(str(chunk.metadata.get("title") or "Source document"))
    ticker = escape(str(chunk.metadata.get("ticker") or "N/A").upper())
    period = escape(str(chunk.metadata.get("period") or "N/A"))
    filing_type = escape(str(chunk.metadata.get("filing_type") or "Document"))
    page_label = escape(str(page))
    pdf_src_attr = escape(pdf_src, quote=True)
    native_pdf_src_attr = escape(native_pdf_src, quote=True)

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Source evidence - {doc_title}</title>
        <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin />
        <link rel="stylesheet" href="{cdn_base}/web/pdf_viewer.css" crossorigin="anonymous" />
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400..650&family=Public+Sans:wght@400;500;600;700&display=swap');

            :root {{
                color-scheme: light;
                --paper: #f3f0e8;
                --paper-deep: #e9e4d8;
                --sheet: #fbfaf6;
                --ink: #152238;
                --ink-soft: #334156;
                --muted: #6e756f;
                --line: #d4d0c6;
                --line-strong: #b7b2a8;
                --cobalt: #2457d6;
                --cobalt-soft: #e7edfb;
                --vermilion: #d55235;
                --vermilion-soft: #f8e9e2;
                --danger: #b8352b;
                --sans: 'Public Sans', 'Avenir Next', sans-serif;
                --serif: 'Newsreader', 'Iowan Old Style', Georgia, serif;
                --shadow: 0 24px 80px rgba(34, 43, 57, 0.09);
            }}

            * {{ box-sizing: border-box; }}
            html, body {{ width: 100%; min-height: 100%; }}
            body {{
                margin: 0;
                color: var(--ink);
                background:
                    linear-gradient(90deg, transparent 0, transparent calc(50% - .5px), rgba(21,34,56,.035) 50%, transparent calc(50% + .5px)),
                    var(--paper);
                font-family: var(--sans);
                -webkit-font-smoothing: antialiased;
            }}
            body::before {{
                position: fixed;
                inset: 0;
                z-index: -1;
                content: '';
                pointer-events: none;
                opacity: 0.3;
                background-image: radial-gradient(rgba(21,34,56,.065) .6px, transparent .6px);
                background-size: 5px 5px;
                mask-image: linear-gradient(to bottom, #000, transparent 78%);
            }}
            button, input, a {{ font: inherit; }}
            button, a {{ -webkit-tap-highlight-color: transparent; }}
            button:focus-visible, a:focus-visible, input:focus-visible {{
                outline: 2px solid var(--cobalt);
                outline-offset: 3px;
            }}

            .shell {{
                display: grid;
                grid-template-rows: auto minmax(0, 1fr);
                min-height: 100vh;
                min-height: 100dvh;
            }}
            .topbar {{
                position: relative;
                z-index: 20;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 1rem;
                width: min(1480px, calc(100% - 64px));
                min-height: 5.75rem;
                margin: 0 auto;
                padding: 0;
                border-bottom: 1px solid var(--line-strong);
            }}
            .wordmark {{ display: flex; align-items: center; gap: 0.7rem; min-width: 0; }}
            .wordmark-mark {{
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 3px;
                flex: 0 0 auto;
                width: 2.375rem;
                height: 2.375rem;
                padding: 8px 7px 6px;
                background: var(--ink);
            }}
            .wordmark-mark i {{ align-self: end; background: var(--sheet); }}
            .wordmark-mark i:nth-child(1) {{ height: 52%; }}
            .wordmark-mark i:nth-child(2) {{ height: 100%; }}
            .wordmark-mark i:nth-child(3) {{ height: 72%; background: var(--vermilion); }}
            .wordmark-copy {{ min-width: 0; }}
            .wordmark-copy strong {{
                display: block;
                overflow: hidden;
                color: var(--ink);
                font-family: var(--serif);
                font-size: 1.1rem;
                font-weight: 590;
                letter-spacing: -0.025em;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}
            .wordmark-copy span {{
                display: block;
                margin-top: 0.12rem;
                color: var(--muted);
                font-size: 0.56rem;
                font-weight: 650;
                letter-spacing: 0.13em;
                text-transform: uppercase;
            }}
            .topbar-actions {{ display: flex; align-items: center; gap: 0.55rem; }}
            .button {{
                display: inline-flex;
                align-items: center;
                justify-content: center;
                min-height: 2.35rem;
                padding: 0.45rem 0.8rem;
                color: var(--ink);
                border: 1px solid var(--line-strong);
                border-radius: 99px;
                background: rgba(251,250,246,.5);
                font-size: 0.74rem;
                font-weight: 500;
                text-decoration: none;
                transition: background 160ms ease, border-color 160ms ease, color 160ms ease, transform 160ms ease;
            }}
            .button:hover {{ color: var(--cobalt); border-color: var(--cobalt); background: var(--sheet); transform: translateY(-1px); }}
            .button.primary {{ color: white; border-color: var(--cobalt); background: var(--cobalt); }}
            .button.primary:hover {{ color: white; background: #1d49ba; }}

            .workspace {{
                display: grid;
                grid-template-columns: minmax(19rem, 23rem) minmax(0, 1fr);
                width: min(1480px, calc(100% - 64px));
                min-height: calc(100vh - 7.75rem);
                min-height: calc(100dvh - 7.75rem);
                margin: 2rem auto;
                border: 1px solid var(--line-strong);
                background: var(--sheet);
                box-shadow: var(--shadow);
            }}
            .evidence {{
                overflow: auto;
                padding: clamp(1.5rem, 3vw, 2.5rem);
                border-right: 1px solid var(--line);
                background: var(--paper);
            }}
            .eyebrow {{
                display: flex;
                align-items: center;
                gap: 0.7rem;
                color: var(--cobalt);
                font-size: 0.62rem;
                font-weight: 720;
                letter-spacing: 0.17em;
                text-transform: uppercase;
            }}
            .eyebrow::before {{ width: 2.6rem; height: 2px; content: ''; background: var(--cobalt); }}
            .document-name {{ margin: 1.5rem 0 0.5rem; color: var(--muted); font-size: 0.7rem; font-weight: 600; line-height: 1.5; }}
            .evidence h1 {{
                margin: 0 0 1.75rem;
                color: var(--ink);
                font-family: var(--serif);
                font-size: clamp(2rem, 2.5vw, 2.8rem);
                font-weight: 470;
                letter-spacing: -0.045em;
                line-height: 0.98;
            }}
            .metadata {{
                display: grid;
                gap: 0;
                margin: 0 0 1.35rem;
                border-top: 1px solid var(--line);
            }}
            .metadata-row {{
                display: grid;
                grid-template-columns: 5.5rem minmax(0, 1fr);
                gap: 0.75rem;
                padding: 0.68rem 0;
                border-bottom: 1px solid var(--line);
            }}
            .metadata dt {{ color: var(--muted); font-size: 0.59rem; font-weight: 700; letter-spacing: 0.11em; text-transform: uppercase; }}
            .metadata dd {{ margin: 0; color: var(--ink-soft); font-size: 0.75rem; font-weight: 600; text-align: right; overflow-wrap: anywhere; }}
            .page-chip {{ color: var(--cobalt); }}
            .excerpt-label {{
                display: flex;
                align-items: center;
                gap: 0.5rem;
                margin-bottom: 0.7rem;
                color: var(--vermilion);
                font-size: 0.61rem;
                font-weight: 720;
                letter-spacing: 0.1em;
                text-transform: uppercase;
            }}
            .excerpt-label::before {{ width: 1.5rem; height: 2px; content: ''; background: var(--vermilion); }}
            .excerpt {{
                margin: 0;
                padding: 1rem;
                color: var(--ink-soft);
                border: 1px solid var(--line);
                border-left: 3px solid var(--vermilion);
                background: var(--sheet);
                font-size: 0.76rem;
                line-height: 1.62;
                white-space: pre-wrap;
                overflow-wrap: anywhere;
            }}
            .excerpt mark {{ padding: 0.05rem 0.12rem; color: var(--ink); background: var(--vermilion-soft); }}
            .evidence-note {{ margin: 0.85rem 0 0; color: var(--muted); font-size: 0.65rem; line-height: 1.5; }}

            .document-panel {{
                display: grid;
                grid-template-rows: auto minmax(0, 1fr);
                min-width: 0;
                min-height: 0;
                background: var(--paper-deep);
            }}
            .document-stage {{ position: relative; min-height: 0; }}
            .viewer-toolbar {{
                position: relative;
                z-index: 10;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 1rem;
                min-height: 3.4rem;
                padding: 0.62rem 0.9rem;
                border-bottom: 1px solid var(--line-strong);
                background: rgba(251,250,246,.94);
                backdrop-filter: blur(14px);
            }}
            .viewer-status {{ display: flex; align-items: center; min-width: 0; gap: 0.55rem; color: var(--ink-soft); font-size: 0.7rem; font-weight: 600; }}
            .status-dot {{ width: 0.42rem; height: 0.42rem; flex: 0 0 auto; border-radius: 50%; background: var(--vermilion); box-shadow: 0 0 0 4px var(--vermilion-soft); }}
            .status-dot.ready {{ background: var(--cobalt); box-shadow: 0 0 0 4px var(--cobalt-soft); }}
            .status-dot.error {{ background: var(--danger); box-shadow: 0 0 0 4px rgba(184,53,43,0.09); }}
            .controls {{ display: flex; align-items: center; gap: 0.35rem; }}
            .control-button, .page-input {{
                height: 2rem;
                color: var(--ink-soft);
                border: 1px solid var(--line-strong);
                border-radius: 99px;
                background: var(--sheet);
                font-size: 0.65rem;
            }}
            .control-button {{ min-width: 2rem; padding: 0 0.55rem; cursor: pointer; }}
            .control-button:hover:not(:disabled) {{ color: var(--cobalt); border-color: var(--cobalt); }}
            .control-button:disabled {{ cursor: wait; opacity: 0.38; }}
            .page-control {{ display: flex; align-items: center; gap: 0.35rem; margin-right: 0.45rem; color: var(--muted); font-size: 0.62rem; font-weight: 650; }}
            .page-input {{ width: 2.8rem; padding: 0 0.35rem; text-align: center; }}
            .zoom-value {{ min-width: 3.2rem; color: var(--muted); font-size: 0.62rem; text-align: center; }}
            #viewerContainer {{ position: absolute; inset: 0; overflow: auto; background: #d9d6cf; }}
            #viewer {{ padding: 1.25rem 0 2.5rem; }}
            .pdfViewer .page {{ margin: 0 auto 1.25rem; border: 1px solid rgba(21,34,56,.1); box-shadow: 0 14px 38px rgba(21,34,56,.16); }}
            .pdfViewer .textLayer .highlight {{ background: rgba(213, 82, 53, 0.34); border-radius: 2px; box-shadow: 0 0 0 1px rgba(213,82,53,0.36); }}
            .pdfViewer .textLayer .highlight.selected {{ background: rgba(36, 87, 214, 0.3); }}
            .loading-state {{
                position: absolute;
                inset: 0;
                z-index: 5;
                display: grid;
                place-items: center;
                color: var(--ink-soft);
                background: var(--paper-deep);
                font-size: 0.7rem;
                font-weight: 650;
                letter-spacing: 0.06em;
            }}
            .loading-state::before {{
                position: absolute;
                width: 2rem;
                height: 2rem;
                margin-top: -3.6rem;
                content: '';
                border: 2px solid rgba(36,87,214,0.14);
                border-top-color: var(--cobalt);
                border-radius: 50%;
                animation: spin 850ms linear infinite;
            }}
            .native-fallback {{ display: none; grid-template-rows: auto minmax(0, 1fr); min-height: 0; background: var(--paper-deep); }}
            .native-message {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 1rem;
                padding: 0.7rem 0.9rem;
                color: var(--ink-soft);
                border-bottom: 1px solid var(--line-strong);
                background: var(--vermilion-soft);
                font-size: 0.7rem;
            }}
            .native-message a {{ color: var(--cobalt); }}
            .native-fallback iframe {{ width: 100%; height: 100%; min-height: 32rem; border: 0; background: white; }}
            @keyframes spin {{ to {{ transform: rotate(360deg); }} }}

            @media (max-width: 860px) {{
                .topbar, .workspace {{ width: min(100% - 32px, 1480px); }}
                .shell {{ display: block; }}
                .workspace {{ display: block; }}
                .evidence {{ overflow: visible; border-right: 0; border-bottom: 1px solid var(--line); }}
                .document-panel {{ height: 76vh; height: 76dvh; min-height: 34rem; }}
            }}
            @media (max-width: 560px) {{
                .topbar {{ align-items: flex-start; }}
                .topbar-actions {{ flex-direction: column; align-items: stretch; }}
                .button {{ min-height: 2rem; padding: 0.35rem 0.6rem; font-size: 0.66rem; }}
                .workspace {{ margin-top: 1rem; }}
                .evidence {{ padding: 1.5rem 1.15rem; }}
                .viewer-toolbar {{ align-items: flex-start; flex-direction: column; }}
                .controls {{ width: 100%; justify-content: flex-end; }}
                .control-button.fit-button, .zoom-value {{ display: none; }}
            }}
            @media (prefers-reduced-motion: reduce) {{
                *, *::before {{ scroll-behavior: auto !important; animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }}
            }}
        </style>
    </head>
    <body>
        <main class="shell">
            <header class="topbar">
                <div class="wordmark">
                    <span class="wordmark-mark" aria-hidden="true"><i></i><i></i><i></i></span>
                    <div class="wordmark-copy">
                        <strong>Filing Intelligence</strong>
                        <span>Research, with receipts.</span>
                    </div>
                </div>
                <nav class="topbar-actions" aria-label="Document actions">
                    <a class="button" href="{native_pdf_src_attr}" target="_blank" rel="noopener">Open raw PDF</a>
                    <a class="button primary" href="{pdf_src_attr}" download>Download</a>
                </nav>
            </header>

            <div class="workspace">
                <aside class="evidence" aria-label="Citation context">
                    <div class="eyebrow">Source / S{page_label}</div>
                    <p class="document-name">{doc_title}</p>
                    <h1>Verify the answer against the source.</h1>
                    <dl class="metadata">
                        <div class="metadata-row"><dt>Ticker</dt><dd>{ticker}</dd></div>
                        <div class="metadata-row"><dt>Period</dt><dd>{period}</dd></div>
                        <div class="metadata-row"><dt>Type</dt><dd>{filing_type}</dd></div>
                        <div class="metadata-row"><dt>Location</dt><dd class="page-chip">Page {page_label}</dd></div>
                    </dl>
                    <div class="excerpt-label">Relevant excerpt</div>
                    <blockquote class="excerpt">{snippet_html or "No excerpt is available for this citation."}</blockquote>
                    <p class="evidence-note">The viewer searches this passage in the PDF text layer. Scanned or reformatted documents may open on the right page without an exact text highlight.</p>
                </aside>

                <section class="document-panel" aria-label="PDF document">
                    <div class="viewer-toolbar">
                        <div class="viewer-status" role="status" aria-live="polite">
                            <span id="statusDot" class="status-dot"></span>
                            <span id="viewerStatus">Loading page {page_label}</span>
                        </div>
                        <div class="controls" aria-label="PDF controls">
                            <label class="page-control">Page
                                <input id="pageNumber" class="page-input" type="number" min="1" value="{page_label}" disabled />
                                <span>/ <span id="pageCount">-</span></span>
                            </label>
                            <button class="control-button" type="button" id="zoomOut" aria-label="Zoom out" disabled>-</button>
                            <span id="zoomValue" class="zoom-value">Fit width</span>
                            <button class="control-button" type="button" id="zoomIn" aria-label="Zoom in" disabled>+</button>
                            <button class="control-button fit-button" type="button" id="fitWidth" disabled>Fit width</button>
                        </div>
                    </div>

                    <div class="document-stage">
                        <div id="viewerContainer" tabindex="0">
                            <div id="loadingState" class="loading-state">Preparing source document</div>
                            <div id="viewer" class="pdfViewer"></div>
                            <div id="nativeFallback" class="native-fallback">
                                <div class="native-message">
                                    <span>The enhanced viewer could not load. The browser's PDF viewer is shown instead.</span>
                                    <a href="{native_pdf_src_attr}" target="_blank" rel="noopener">Open in a new tab</a>
                                </div>
                                <iframe title="Source PDF fallback" data-src="{native_pdf_src_attr}"></iframe>
                            </div>
                        </div>
                    </div>
                </section>
            </div>
        </main>

        <script type="module">
            const pdfUrl = {pdf_url_js};
            const targetPage = {page_js};
            const searchPhrases = {search_phrases_js};
            const cdnBase = {_json_for_script(cdn_base)};
            const loadingState = document.getElementById("loadingState");
            const viewer = document.getElementById("viewer");
            const nativeFallback = document.getElementById("nativeFallback");
            const statusText = document.getElementById("viewerStatus");
            const statusDot = document.getElementById("statusDot");
            const pageNumber = document.getElementById("pageNumber");
            const pageCount = document.getElementById("pageCount");
            const zoomValue = document.getElementById("zoomValue");
            const controls = [...document.querySelectorAll(".control-button")];
            let activeSearchIndex = -1;
            let searchFinished = false;

            function setStatus(message, state = "loading") {{
                statusText.textContent = message;
                statusDot.className = `status-dot ${{state === "ready" ? "ready" : state === "error" ? "error" : ""}}`;
            }}

            function showNativeFallback() {{
                loadingState.style.display = "none";
                viewer.style.display = "none";
                nativeFallback.style.display = "grid";
                const frame = nativeFallback.querySelector("iframe");
                if (!frame.src) frame.src = frame.dataset.src;
                controls.forEach((control) => control.disabled = true);
                pageNumber.disabled = true;
                setStatus(`Native PDF viewer - page ${{targetPage}}`, "error");
            }}

            function updateZoom(pdfViewer) {{
                const scaleValue = pdfViewer.currentScaleValue;
                zoomValue.textContent = scaleValue === "page-width"
                    ? "Fit width"
                    : `${{Math.round(pdfViewer.currentScale * 100)}}%`;
            }}

            function activeSearchPhrase() {{
                return searchPhrases[activeSearchIndex] || "";
            }}

            try {{
                setStatus(`Loading page ${{targetPage}}`);
                const pdfjsLib = await import(`${{cdnBase}}/build/pdf.min.mjs`);
                const pdfjsViewer = await import(`${{cdnBase}}/web/pdf_viewer.mjs`);
                pdfjsLib.GlobalWorkerOptions.workerSrc = `${{cdnBase}}/build/pdf.worker.min.mjs`;

                const eventBus = new pdfjsViewer.EventBus();
                const linkService = new pdfjsViewer.PDFLinkService({{ eventBus }});
                const findController = new pdfjsViewer.PDFFindController({{ eventBus, linkService }});
                const container = document.getElementById("viewerContainer");
                const pdfViewer = new pdfjsViewer.PDFViewer({{
                    container,
                    viewer,
                    eventBus,
                    linkService,
                    findController,
                    textLayerMode: 2,
                    annotationMode: 2,
                }});
                linkService.setViewer(pdfViewer);
                window.pdfViewerInstance = pdfViewer;

                function searchNextCandidate() {{
                    activeSearchIndex += 1;
                    if (activeSearchIndex >= searchPhrases.length) {{
                        searchFinished = true;
                        setStatus(`Page ${{pdfViewer.currentPageNumber}} ready - exact text not found`, "ready");
                        return;
                    }}
                    const query = activeSearchPhrase();
                    setStatus(`Searching cited text on page ${{pdfViewer.currentPageNumber}}`);
                    eventBus.dispatch("find", {{
                        source: window,
                        type: "",
                        query,
                        caseSensitive: false,
                        entireWord: false,
                        highlightAll: true,
                        findPrevious: false,
                        matchDiacritics: false,
                    }});
                }}

                function navigateToRequestedPage() {{
                    if (!pageNumber.value) return;
                    const requested = Number.parseInt(pageNumber.value, 10);
                    const currentPage = pdfViewer.currentPageNumber;
                    const nextPage = Number.isFinite(requested)
                        ? Math.max(1, Math.min(requested, pdfViewer.pagesCount))
                        : currentPage;
                    linkService.goToPage(nextPage);
                    pageNumber.value = nextPage;
                }}

                eventBus.on("pagesinit", () => {{
                    const safePage = Math.min(targetPage, pdfViewer.pagesCount);
                    pdfViewer.currentScaleValue = "page-width";
                    pdfViewer.currentPageNumber = safePage;
                    pageNumber.value = safePage;
                    pageNumber.max = pdfViewer.pagesCount;
                    pageNumber.disabled = false;
                    pageCount.textContent = pdfViewer.pagesCount;
                    controls.forEach((control) => control.disabled = false);
                    loadingState.style.display = "none";
                    updateZoom(pdfViewer);
                    setStatus(`Page ${{safePage}} ready`, "ready");

                    if (searchPhrases.length) searchNextCandidate();
                }});

                eventBus.on("updatefindcontrolstate", (event) => {{
                    if (searchFinished || event.rawQuery !== activeSearchPhrase()) return;
                    if (event.state === 1) {{
                        searchNextCandidate();
                    }} else if (event.state === 0 || event.state === 2) {{
                        searchFinished = true;
                        setStatus(`Citation highlighted on page ${{pdfViewer.currentPageNumber}}`, "ready");
                    }}
                }});
                eventBus.on("pagechanging", (event) => {{ pageNumber.value = event.pageNumber; }});
                eventBus.on("scalechanging", () => updateZoom(pdfViewer));

                document.getElementById("zoomIn").addEventListener("click", () => {{
                    pdfViewer.currentScale = Math.min(pdfViewer.currentScale * 1.15, 5);
                    updateZoom(pdfViewer);
                }});
                document.getElementById("zoomOut").addEventListener("click", () => {{
                    pdfViewer.currentScale = Math.max(pdfViewer.currentScale / 1.15, 0.25);
                    updateZoom(pdfViewer);
                }});
                document.getElementById("fitWidth").addEventListener("click", () => {{
                    pdfViewer.currentScaleValue = "page-width";
                    updateZoom(pdfViewer);
                }});
                pageNumber.addEventListener("input", navigateToRequestedPage);
                pageNumber.addEventListener("change", navigateToRequestedPage);
                pageNumber.addEventListener("keydown", (event) => {{
                    if (event.key !== "Enter") return;
                    event.preventDefault();
                    navigateToRequestedPage();
                }});

                const loadingTask = pdfjsLib.getDocument({{
                    url: pdfUrl,
                    cMapUrl: `${{cdnBase}}/cmaps/`,
                    cMapPacked: true,
                    standardFontDataUrl: `${{cdnBase}}/standard_fonts/`,
                    withCredentials: false,
                }});
                const pdfDocument = await loadingTask.promise;
                pdfViewer.setDocument(pdfDocument);
                linkService.setDocument(pdfDocument, null);
            }} catch (error) {{
                console.error("Enhanced PDF viewer failed", error);
                showNativeFallback();
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(html)
