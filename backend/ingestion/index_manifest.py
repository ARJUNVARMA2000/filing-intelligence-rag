from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

INDEX_SCHEMA_VERSION = 2
DEFAULT_EMBEDDING_NAME = "chroma-default/all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_DIMENSION = 384
MANIFEST_FILENAME = "index_manifest.json"


@dataclass(frozen=True)
class IndexManifest:
    collection_name: str
    schema_version: int = INDEX_SCHEMA_VERSION
    embedding_name: str = DEFAULT_EMBEDDING_NAME
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION
    distance_metric: str = "cosine"
    document_count: int = 0
    chunk_count: int = 0
    built_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    chunking: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, persist_directory: Path) -> IndexManifest | None:
        path = persist_directory / MANIFEST_FILENAME
        if not path.is_file():
            return None
        return cls(**json.loads(path.read_text(encoding="utf-8")))

    def validate_compatible(self, collection_name: str) -> None:
        expected = (
            INDEX_SCHEMA_VERSION,
            DEFAULT_EMBEDDING_NAME,
            DEFAULT_EMBEDDING_DIMENSION,
            "cosine",
            collection_name,
        )
        actual = (
            self.schema_version,
            self.embedding_name,
            self.embedding_dimension,
            self.distance_metric,
            self.collection_name,
        )
        if actual != expected:
            raise ValueError(
                "Index manifest is incompatible with this runtime. "
                f"Expected {expected!r}, received {actual!r}. Rebuild the index."
            )

    def write(self, persist_directory: Path) -> Path:
        persist_directory.mkdir(parents=True, exist_ok=True)
        path = persist_directory / MANIFEST_FILENAME
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
        return path
