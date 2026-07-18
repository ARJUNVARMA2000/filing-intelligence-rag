from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

from tqdm import tqdm

from ..vectorstore.chroma_store import ChromaVectorStore
from .chunking import ChunkingConfig, chunk_document
from .index_manifest import IndexManifest
from .metadata_schema import Chunk, Document

DEFAULT_CHUNKING_CONFIG = ChunkingConfig()


def build_chunks_for_documents(
    documents: Iterable[Document],
    config: ChunkingConfig | None = None,
) -> list[Chunk]:
    """Build deterministic chunks and embed their stable IDs in metadata."""

    active_config = config or DEFAULT_CHUNKING_CONFIG
    return [chunk for document in documents for chunk in chunk_document(document, active_config)]


def index_documents(
    documents: Iterable[Document],
    *,
    openai_client: object | None = None,
    persist_dir: Path,
    collection_name: str = "financial_docs",
    replace: bool = False,
    chunking_config: ChunkingConfig | None = None,
) -> IndexManifest:
    """Index documents with Chroma's explicit bundled default embedding contract.

    ``openai_client`` remains as a compatibility-only keyword for existing CLI
    callers. Provider embeddings are deliberately neither requested nor discarded.
    """

    del openai_client
    document_list = list(documents)
    config = chunking_config or DEFAULT_CHUNKING_CONFIG
    chunks = build_chunks_for_documents(document_list, config)
    if not chunks:
        raise ValueError("No indexable chunks were produced from the supplied documents.")

    vector_store = ChromaVectorStore(
        persist_directory=str(persist_dir),
        collection_name=collection_name,
    )
    if replace:
        vector_store.reset()
    else:
        vector_store.delete_documents([document.metadata.doc_id for document in document_list])

    batch_size = 64
    for start in tqdm(range(0, len(chunks), batch_size), desc="Indexing chunks"):
        vector_store.upsert(chunks[start : start + batch_size])

    vector_store.validate_embedding_contract()
    stats = vector_store.get_stats()
    manifest = IndexManifest(
        collection_name=collection_name,
        document_count=int(stats["total_documents"]),
        chunk_count=int(stats["total_chunks"]),
        chunking=asdict(config),
    )
    manifest.write(persist_dir)
    return manifest
