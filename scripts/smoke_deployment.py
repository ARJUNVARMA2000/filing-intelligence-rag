"""End-to-end smoke test for the deployed Filing Intelligence RAG services."""

from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


def request_json(url: str, *, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    request = Request(quote(url, safe=":/?=&"), data=data, headers=headers)
    try:
        with urlopen(request, timeout=120) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        body = json.loads(exc.read().decode() or "{}")
        return exc.code, body


def fetch(url: str, *, headers: dict[str, str] | None = None) -> tuple[int, str, dict, bytes]:
    request = Request(quote(url, safe=":/?=&"), headers=headers or {})
    with urlopen(request, timeout=120) as response:
        return (
            response.status,
            response.headers.get_content_type(),
            dict(response.headers.items()),
            response.read(),
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True)
    parser.add_argument("--frontend", required=True)
    parser.add_argument("--question", default="What was NVIDIA revenue in Q3 2026?")
    parser.add_argument("--ticker", default="NVDA")
    parser.add_argument("--period", default="Q3-2026")
    args = parser.parse_args()

    backend = args.backend.rstrip("/")
    frontend = args.frontend.rstrip("/")

    status, ready = request_json(f"{backend}/health/ready")
    assert status == 200 and ready.get("index_chunks", 0) > 0, ready

    status, frontend_health = request_json(f"{frontend}/api/health")
    assert status == 200 and frontend_health.get("ready") is True, frontend_health
    assert frontend_health.get("indexChunks", 0) > 0, frontend_health

    status, content_type, _, body = fetch(frontend)
    assert status == 200 and content_type == "text/html"
    assert b"Filing Intelligence" in body

    status, _ = request_json(
        f"{backend}/chat/parse-query",
        payload={"question": args.question},
    )
    assert status == 401, "Paid chat routes must reject callers without a frontend identity token."

    # The paid route is intentionally inaccessible from a non-GCP caller. The
    # browser/UI test exercises the authorized frontend-to-backend path.
    # Use the public index metadata plus citation endpoint for storage checks.
    # A known citation is stable because the versioned index is bundled in the image.
    highlight_path = (
        "/documents/NVDA_Q3-2026_NVIDIA - Q3 2026/"
        "chunks/NVDA_Q3-2026_NVIDIA - Q3 2026_chunk_1/viewer"
    )

    document_url = (
        urljoin(f"{backend}/", highlight_path.lstrip("/")).removesuffix("/viewer") + "/file"
    )
    status, content_type, headers, body = fetch(
        document_url,
        headers={"Range": "bytes=0-127"},
    )
    assert status == 206 and content_type == "application/pdf" and body.startswith(b"%PDF")
    assert len(body) == 128
    assert headers.get("Accept-Ranges") == "bytes"
    assert headers.get("Content-Range", "").startswith("bytes 0-127/")

    print(
        json.dumps(
            {
                "status": "passed",
                "index_chunks": ready["index_chunks"],
                "range_bytes": len(body),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
