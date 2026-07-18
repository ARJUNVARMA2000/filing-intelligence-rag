from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .metadata_schema import Document


def sidecar_path(document_path: Path) -> Path:
    """Return the metadata sidecar path for a downloaded source document."""

    return document_path.with_suffix(document_path.suffix + ".metadata.json")


def load_sidecar(document_path: Path) -> dict[str, Any]:
    path = sidecar_path(document_path)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid source metadata sidecar: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Source metadata sidecar must contain an object: {path}")
    return value


def apply_sidecar(document: Document, values: dict[str, Any]) -> Document:
    """Apply trusted, normalized source metadata to a parsed document."""

    metadata = document.metadata
    for field in (
        "source",
        "source_id",
        "source_created_at",
        "source_updated_at",
        "fetched_at",
        "event_date",
        "content_sha256",
        "company_id",
        "event_id",
        "source_type_id",
    ):
        value = values.get(field)
        if value is not None:
            setattr(metadata, field, str(value))

    for field in ("doc_id", "ticker", "filing_type", "period", "source_url", "title"):
        value = values.get(field)
        if value not in (None, ""):
            setattr(metadata, field, str(value))
    return document


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
