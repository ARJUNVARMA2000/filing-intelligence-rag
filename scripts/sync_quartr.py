from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.ingestion.source_metadata import sidecar_path, write_json_atomic  # noqa: E402
from backend.ingestion.sources.quartr_client import (  # noqa: E402
    QuartrClient,
    QuartrResource,
    ResourceKind,
)

DEFAULT_STATE_PATH = Path("data/processed/quartr_sync_state.json")
DEFAULT_RAW_ROOT = Path("data/raw")


def _parse_iso8601(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _format_iso8601(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-_") or "document"


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "watermarks": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid Quartr sync state: {path}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("watermarks", {}), dict):
        raise ValueError(f"Invalid Quartr sync state shape: {path}")
    value.setdefault("version", 1)
    value.setdefault("watermarks", {})
    return value


def _watermark_key(ticker: str, kind: ResourceKind) -> str:
    return f"{ticker.upper()}:{kind}"


def _initial_start_date(lookback_days: int) -> str:
    return _format_iso8601(datetime.now(UTC) - timedelta(days=lookback_days))


def _incremental_start(watermark: str, overlap_minutes: int) -> str:
    return _format_iso8601(_parse_iso8601(watermark) - timedelta(minutes=overlap_minutes))


def _resource_paths(raw_root: Path, ticker: str, resource: QuartrResource) -> tuple[Path, Path]:
    extension = ".pdf" if resource.kind == "reports" else ".json"
    stable_id = resource.event_id if resource.kind == "transcripts" else resource.id
    name = _safe_filename(f"quartr_{resource.kind}_{stable_id}") + extension
    document_path = raw_root / ticker.lower() / name
    return document_path, sidecar_path(document_path)


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def _metadata_for(
    ticker: str,
    resource: QuartrResource,
    *,
    content_sha256: str,
    fetched_at: str,
) -> dict[str, Any]:
    event = resource.event
    stable_id = resource.event_id if resource.kind == "transcripts" else resource.id
    return {
        "schema_version": 1,
        "source": "quartr",
        "resource_kind": resource.kind,
        "source_id": str(resource.id),
        "doc_id": f"quartr_{resource.kind}_{stable_id}",
        "ticker": ticker.upper(),
        "period": resource.period,
        "filing_type": "report" if resource.kind == "reports" else "transcript",
        "title": str(event.get("title") or f"{ticker.upper()} {resource.period} {resource.kind}"),
        "source_url": resource.file_url,
        "source_created_at": resource.created_at,
        "source_updated_at": resource.updated_at,
        "fetched_at": fetched_at,
        "event_date": str(event.get("date") or ""),
        "content_sha256": content_sha256,
        "company_id": str(resource.company_id),
        "event_id": str(resource.event_id),
        "source_type_id": str(resource.type_id),
    }


def _existing_is_current(
    metadata_path: Path, resource: QuartrResource, document_path: Path
) -> bool:
    if not metadata_path.exists() or not document_path.exists():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(metadata, dict)
        and str(metadata.get("source_id")) == str(resource.id)
        and metadata.get("source_updated_at") == resource.updated_at
        and bool(metadata.get("content_sha256"))
    )


def sync_ticker_kind(
    client: QuartrClient,
    *,
    ticker: str,
    kind: ResourceKind,
    raw_root: Path,
    state: dict[str, Any],
    lookback_days: int,
    overlap_minutes: int,
    full: bool,
) -> dict[str, int]:
    key = _watermark_key(ticker, kind)
    watermark = None if full else state["watermarks"].get(key)
    query: dict[str, Any] = {}
    if watermark:
        query["updated_after"] = _incremental_start(str(watermark), overlap_minutes)
    else:
        query["start_date"] = _initial_start_date(lookback_days)
    if kind == "transcripts":
        query["type_ids"] = (15, 22)

    resources = list(client.iter_resources(kind, tickers=[ticker], **query))
    if kind == "transcripts":
        # Quartr can return raw (15) and edited (22) transcripts for one event.
        # Keep one canonical document per event and prefer the edited version.
        preferred: dict[int, QuartrResource] = {}
        for resource in resources:
            current = preferred.get(resource.event_id)
            if (
                current is None
                or (resource.type_id == 22 and current.type_id != 22)
                or (
                    resource.type_id == current.type_id and resource.updated_at > current.updated_at
                )
            ):
                preferred[resource.event_id] = resource
        resources = list(preferred.values())
    newest_updated_at = str(watermark or "")
    downloaded = 0
    unchanged = 0
    seen = 0
    for resource in resources:
        seen += 1
        document_path, metadata_path = _resource_paths(raw_root, ticker, resource)
        if _existing_is_current(metadata_path, resource, document_path):
            unchanged += 1
        else:
            content = client.download(resource)
            digest = hashlib.sha256(content).hexdigest()
            fetched_at = _format_iso8601(datetime.now(UTC))
            _write_bytes_atomic(document_path, content)
            write_json_atomic(
                metadata_path,
                _metadata_for(
                    ticker,
                    resource,
                    content_sha256=digest,
                    fetched_at=fetched_at,
                ),
            )
            downloaded += 1
        if resource.updated_at > newest_updated_at:
            newest_updated_at = resource.updated_at

    # Advance only after the complete cursor sequence and every download succeeded.
    if newest_updated_at:
        state["watermarks"][key] = newest_updated_at
    return {"seen": seen, "downloaded": downloaded, "unchanged": unchanged}


def parse_tickers(values: Iterable[str]) -> list[str]:
    tickers: set[str] = set()
    for value in values:
        tickers.update(item.strip().upper() for item in value.split(",") if item.strip())
    return sorted(tickers)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Incrementally synchronize reports and transcripts from the Quartr Public API."
    )
    parser.add_argument(
        "--tickers",
        action="append",
        default=[],
        help="Comma-separated tickers; may be repeated. Defaults to DATA_TICKERS.",
    )
    parser.add_argument(
        "--kind",
        choices=("reports", "transcripts", "all"),
        default="all",
    )
    parser.add_argument("--lookback-days", type=int, default=730)
    parser.add_argument("--overlap-minutes", type=int, default=5)
    parser.add_argument(
        "--full", action="store_true", help="Ignore watermarks and rescan the lookback window."
    )
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    args = parser.parse_args()

    tickers = parse_tickers([*args.tickers, os.environ.get("DATA_TICKERS", "")])
    if not tickers:
        parser.error("Provide --tickers or DATA_TICKERS.")
    if args.lookback_days < 1:
        parser.error("--lookback-days must be positive.")
    if args.overlap_minutes < 0:
        parser.error("--overlap-minutes cannot be negative.")

    api_key = os.environ.get("QUARTR_API_KEY", "")
    base_url = os.environ.get("QUARTR_API_BASE_URL", "https://api.quartr.com/public/v3")
    state = _load_state(args.state)
    kinds: tuple[ResourceKind, ...] = (
        ("reports", "transcripts") if args.kind == "all" else (args.kind,)
    )

    totals = {"seen": 0, "downloaded": 0, "unchanged": 0}
    with QuartrClient(api_key, base_url=base_url) as client:
        for ticker in tickers:
            for kind in kinds:
                result = sync_ticker_kind(
                    client,
                    ticker=ticker,
                    kind=kind,
                    raw_root=args.raw_root,
                    state=state,
                    lookback_days=args.lookback_days,
                    overlap_minutes=args.overlap_minutes,
                    full=args.full,
                )
                for name, value in result.items():
                    totals[name] += value
                print(f"{ticker} {kind}: {result}")
                write_json_atomic(args.state, state)

    print(f"Quartr sync complete: {totals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
