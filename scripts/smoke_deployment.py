"""End-to-end smoke test for the deployed Financial RAG services."""

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


def fetch(url: str) -> tuple[int, str, bytes]:
    with urlopen(quote(url, safe=":/?=&"), timeout=120) as response:
        return response.status, response.headers.get_content_type(), response.read()


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

    status, _, _ = fetch(f"{frontend}/_stcore/health")
    assert status == 200

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
    status, content_type, body = fetch(document_url)
    assert status == 200 and content_type == "application/pdf" and body.startswith(b"%PDF")

    print(
        json.dumps(
            {
                "status": "passed",
                "index_chunks": ready["index_chunks"],
                "document_bytes": len(body),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
