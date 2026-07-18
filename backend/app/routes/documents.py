from __future__ import annotations

import json
from collections.abc import Iterator
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

from ...vectorstore.chroma_store import ChromaVectorStore
from ..dependencies import get_app_settings
from ..services.highlight import build_search_phrase, source_text

router = APIRouter()


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


def _load_document_from_bucket(path_value: str) -> tuple[Iterator[bytes], str] | None:
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

    def stream() -> Iterator[bytes]:
        with blob.open("rb") as source:
            while content := source.read(1024 * 1024):
                yield content

    return stream(), relative.name


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

    filename = file_path.name if file_path else cloud_document[1]
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
    }
    if file_path:
        return FileResponse(file_path, media_type=media_type, headers=headers)
    return StreamingResponse(cloud_document[0], media_type=media_type, headers=headers)


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
    pdf_src = _document_endpoint(doc_id, chunk_id, "file")
    native_pdf_src = f"{pdf_src}#page={page}"
    snippet_html = _format_snippet(source_text(chunk.text), phrase)

    pdf_url_js = _json_for_script(pdf_src)
    phrase_js = _json_for_script(phrase)
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
            @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600&family=Newsreader:opsz,wght@6..72,500&display=swap');

            :root {{
                color-scheme: dark;
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
                --sans: 'IBM Plex Sans', 'Segoe UI', sans-serif;
                --serif: 'Newsreader', Georgia, serif;
                --mono: 'IBM Plex Mono', Consolas, monospace;
            }}

            * {{ box-sizing: border-box; }}
            html, body {{ width: 100%; min-height: 100%; }}
            body {{
                margin: 0;
                color: var(--paper);
                background:
                    radial-gradient(circle at 92% -20%, rgba(184, 243, 107, 0.09), transparent 28rem),
                    var(--ink);
                font-family: var(--sans);
            }}
            body::before {{
                position: fixed;
                inset: 0;
                z-index: -1;
                content: '';
                pointer-events: none;
                opacity: 0.28;
                background-image:
                    linear-gradient(rgba(255,255,255,0.018) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(255,255,255,0.018) 1px, transparent 1px);
                background-size: 44px 44px;
            }}
            button, input, a {{ font: inherit; }}
            button, a {{ -webkit-tap-highlight-color: transparent; }}
            button:focus-visible, a:focus-visible, input:focus-visible {{
                outline: 2px solid var(--signal);
                outline-offset: 2px;
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
                min-height: 4.25rem;
                padding: 0.75rem 1.15rem;
                border-bottom: 1px solid var(--line);
                background: rgba(10, 13, 12, 0.94);
                backdrop-filter: blur(16px);
            }}
            .wordmark {{ display: flex; align-items: center; gap: 0.7rem; min-width: 0; }}
            .wordmark-mark {{
                display: grid;
                flex: 0 0 auto;
                place-items: center;
                width: 2rem;
                height: 2rem;
                color: var(--ink);
                background: var(--signal);
                border-radius: 2px;
                font-family: var(--mono);
                font-size: 0.7rem;
                font-weight: 500;
            }}
            .wordmark-copy {{ min-width: 0; }}
            .wordmark-copy strong {{
                display: block;
                overflow: hidden;
                color: var(--paper);
                font-size: 0.86rem;
                font-weight: 500;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}
            .wordmark-copy span {{
                display: block;
                margin-top: 0.12rem;
                color: var(--muted);
                font-family: var(--mono);
                font-size: 0.58rem;
                letter-spacing: 0.11em;
                text-transform: uppercase;
            }}
            .topbar-actions {{ display: flex; align-items: center; gap: 0.55rem; }}
            .button {{
                display: inline-flex;
                align-items: center;
                justify-content: center;
                min-height: 2.35rem;
                padding: 0.45rem 0.8rem;
                color: var(--paper);
                border: 1px solid var(--line-strong);
                border-radius: 3px;
                background: var(--panel);
                font-size: 0.74rem;
                font-weight: 500;
                text-decoration: none;
                transition: border-color 160ms ease, color 160ms ease, transform 160ms ease;
            }}
            .button:hover {{ color: var(--signal); border-color: rgba(184,243,107,0.48); transform: translateY(-1px); }}
            .button.primary {{ color: var(--ink); border-color: var(--signal); background: var(--signal); }}
            .button.primary:hover {{ color: var(--ink); background: #c5fa82; }}

            .workspace {{
                display: grid;
                grid-template-columns: minmax(17rem, 22rem) minmax(0, 1fr);
                min-height: 0;
            }}
            .evidence {{
                overflow: auto;
                padding: 1.5rem;
                border-right: 1px solid var(--line);
                background: rgba(13, 18, 16, 0.88);
            }}
            .eyebrow {{
                color: var(--signal);
                font-family: var(--mono);
                font-size: 0.6rem;
                letter-spacing: 0.14em;
                text-transform: uppercase;
            }}
            .evidence h1 {{
                margin: 0.75rem 0 1.35rem;
                color: var(--paper);
                font-family: var(--serif);
                font-size: clamp(1.6rem, 2.2vw, 2.3rem);
                font-weight: 500;
                line-height: 1.02;
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
            .metadata dt {{ color: var(--muted); font-family: var(--mono); font-size: 0.61rem; letter-spacing: 0.08em; text-transform: uppercase; }}
            .metadata dd {{ margin: 0; color: var(--paper-soft); font-size: 0.75rem; text-align: right; overflow-wrap: anywhere; }}
            .page-chip {{ color: var(--signal); font-family: var(--mono); }}
            .excerpt-label {{
                display: flex;
                align-items: center;
                gap: 0.5rem;
                margin-bottom: 0.7rem;
                color: var(--amber);
                font-family: var(--mono);
                font-size: 0.61rem;
                letter-spacing: 0.1em;
                text-transform: uppercase;
            }}
            .excerpt-label::before {{ width: 1.5rem; height: 1px; content: ''; background: var(--amber); }}
            .excerpt {{
                margin: 0;
                padding: 1rem;
                color: var(--paper-soft);
                border: 1px solid rgba(220, 182, 109, 0.22);
                border-left: 2px solid var(--amber);
                border-radius: 2px;
                background: rgba(220, 182, 109, 0.055);
                font-size: 0.76rem;
                line-height: 1.62;
                white-space: pre-wrap;
                overflow-wrap: anywhere;
            }}
            .excerpt mark {{ padding: 0.05rem 0.12rem; color: var(--ink); background: var(--amber); }}
            .evidence-note {{ margin: 0.85rem 0 0; color: var(--muted); font-size: 0.65rem; line-height: 1.5; }}

            .document-panel {{
                display: grid;
                grid-template-rows: auto minmax(0, 1fr);
                min-width: 0;
                min-height: 0;
                background: #272c29;
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
                border-bottom: 1px solid rgba(0,0,0,0.42);
                background: #111714;
            }}
            .viewer-status {{ display: flex; align-items: center; min-width: 0; gap: 0.55rem; color: var(--paper-soft); font-size: 0.7rem; }}
            .status-dot {{ width: 0.42rem; height: 0.42rem; flex: 0 0 auto; border-radius: 50%; background: var(--amber); box-shadow: 0 0 0 4px rgba(220,182,109,0.08); }}
            .status-dot.ready {{ background: var(--signal); box-shadow: 0 0 0 4px var(--signal-soft); }}
            .status-dot.error {{ background: var(--danger); box-shadow: 0 0 0 4px rgba(239,143,128,0.08); }}
            .controls {{ display: flex; align-items: center; gap: 0.35rem; }}
            .control-button, .page-input {{
                height: 2rem;
                color: var(--paper-soft);
                border: 1px solid var(--line-strong);
                border-radius: 2px;
                background: var(--panel);
                font-family: var(--mono);
                font-size: 0.65rem;
            }}
            .control-button {{ min-width: 2rem; padding: 0 0.55rem; cursor: pointer; }}
            .control-button:hover:not(:disabled) {{ color: var(--signal); border-color: rgba(184,243,107,0.45); }}
            .control-button:disabled {{ cursor: wait; opacity: 0.38; }}
            .page-control {{ display: flex; align-items: center; gap: 0.35rem; margin-right: 0.45rem; color: var(--muted); font-family: var(--mono); font-size: 0.62rem; }}
            .page-input {{ width: 2.8rem; padding: 0 0.35rem; text-align: center; }}
            .zoom-value {{ min-width: 3.2rem; color: var(--muted); font-family: var(--mono); font-size: 0.62rem; text-align: center; }}
            #viewerContainer {{ position: absolute; inset: 0; overflow: auto; background: #343a36; }}
            #viewer {{ padding: 1.25rem 0 2.5rem; }}
            .pdfViewer .page {{ margin: 0 auto 1.25rem; border: 0; box-shadow: 0 10px 34px rgba(0,0,0,0.28); }}
            .pdfViewer .textLayer .highlight {{ background: rgba(184, 243, 107, 0.62); border-radius: 2px; box-shadow: 0 0 0 1px rgba(85,118,42,0.35); }}
            .pdfViewer .textLayer .highlight.selected {{ background: rgba(220, 182, 109, 0.82); }}
            .loading-state {{
                position: absolute;
                inset: 0;
                z-index: 5;
                display: grid;
                place-items: center;
                color: var(--paper-soft);
                background: #343a36;
                font-family: var(--mono);
                font-size: 0.7rem;
                letter-spacing: 0.06em;
            }}
            .loading-state::before {{
                position: absolute;
                width: 2rem;
                height: 2rem;
                margin-top: -3.6rem;
                content: '';
                border: 2px solid rgba(184,243,107,0.16);
                border-top-color: var(--signal);
                border-radius: 50%;
                animation: spin 850ms linear infinite;
            }}
            .native-fallback {{ display: none; grid-template-rows: auto minmax(0, 1fr); min-height: 0; background: #343a36; }}
            .native-message {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 1rem;
                padding: 0.7rem 0.9rem;
                color: var(--paper-soft);
                border-bottom: 1px solid rgba(0,0,0,0.35);
                background: rgba(239,143,128,0.07);
                font-size: 0.7rem;
            }}
            .native-message a {{ color: var(--signal); }}
            .native-fallback iframe {{ width: 100%; height: 100%; min-height: 32rem; border: 0; background: white; }}
            @keyframes spin {{ to {{ transform: rotate(360deg); }} }}

            @media (max-width: 860px) {{
                .shell {{ display: block; }}
                .workspace {{ display: block; }}
                .evidence {{ overflow: visible; border-right: 0; border-bottom: 1px solid var(--line); }}
                .document-panel {{ height: 76vh; height: 76dvh; min-height: 34rem; }}
            }}
            @media (max-width: 560px) {{
                .topbar {{ align-items: flex-start; }}
                .topbar-actions {{ flex-direction: column; align-items: stretch; }}
                .button {{ min-height: 2rem; padding: 0.35rem 0.6rem; font-size: 0.66rem; }}
                .evidence {{ padding: 1.15rem; }}
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
                    <span class="wordmark-mark">S{page_label}</span>
                    <div class="wordmark-copy">
                        <strong>{doc_title}</strong>
                        <span>Source evidence viewer</span>
                    </div>
                </div>
                <nav class="topbar-actions" aria-label="Document actions">
                    <a class="button" href="{native_pdf_src_attr}" target="_blank" rel="noopener">Open raw PDF</a>
                    <a class="button primary" href="{pdf_src_attr}" download>Download</a>
                </nav>
            </header>

            <div class="workspace">
                <aside class="evidence" aria-label="Citation context">
                    <div class="eyebrow">Cited passage</div>
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
            const searchPhrase = {phrase_js};
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
            let searchTimeout;

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

                    if (searchPhrase) {{
                        setStatus(`Searching cited text on page ${{safePage}}`);
                        eventBus.dispatch("find", {{
                            source: window,
                            type: "",
                            query: searchPhrase,
                            phraseSearch: true,
                            caseSensitive: false,
                            entireWord: false,
                            highlightAll: true,
                            findPrevious: false,
                            matchDiacritics: false,
                        }});
                        searchTimeout = window.setTimeout(() => {{
                            setStatus(`Page ${{pdfViewer.currentPageNumber}} ready - exact text not found`, "ready");
                        }}, 5000);
                    }}
                }});

                eventBus.on("updatefindcontrolstate", (event) => {{
                    if (event.state === 1) {{
                        window.clearTimeout(searchTimeout);
                        setStatus(`Page ${{pdfViewer.currentPageNumber}} ready - exact text not found`, "ready");
                    }} else if (event.state === 0 || event.state === 2) {{
                        window.clearTimeout(searchTimeout);
                        setStatus(`Citation highlighted on page ${{pdfViewer.currentPageNumber}}`, "ready");
                    }}
                }});
                eventBus.on("updatefindmatchescount", (event) => {{
                    if (event.matchesCount?.total > 0) {{
                        window.clearTimeout(searchTimeout);
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
                pageNumber.addEventListener("change", () => {{
                    const nextPage = Math.max(1, Math.min(Number(pageNumber.value), pdfViewer.pagesCount));
                    pdfViewer.currentPageNumber = nextPage;
                    pageNumber.value = nextPage;
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
