from __future__ import annotations

import argparse
import re

# Ensure we're using absolute paths
import sys
from pathlib import Path

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    import codecs

    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from backend.app.config import get_settings  # noqa: E402
from backend.ingestion.index_builder import index_documents  # noqa: E402
from backend.ingestion.metadata_schema import Document  # noqa: E402
from backend.ingestion.parsers.html_parser import parse_html_to_document  # noqa: E402
from backend.ingestion.parsers.pdf_parser import parse_pdf_to_document  # noqa: E402
from backend.ingestion.parsers.quartr_transcript_parser import (  # noqa: E402
    parse_quartr_transcript_to_document,
)
from backend.ingestion.parsers.text_normalizer import tag_sections  # noqa: E402
from backend.ingestion.source_metadata import apply_sidecar, load_sidecar  # noqa: E402


def extract_period_from_filename(filename: str) -> str | None:
    """
    Extract period from filename.

    Handles formats like:
    - "Amazon - Q3 2025.pdf" -> "Q3-2025"
    - "Amazon_Q1_2025.pdf" -> "Q1-2025"
    - "Apple Q2 2025 Earnings.pdf" -> "Q2-2025"
    - "MSFT-Q4-2024.pdf" -> "Q4-2024"
    """
    # Pattern: Q1-Q4 followed by 4-digit year
    match = re.search(r"Q([1-4])\s*[-_]?\s*(\d{4})", filename, re.IGNORECASE)
    if match:
        return f"Q{match.group(1)}-{match.group(2)}"

    # Pattern: FY or Annual followed by year
    match = re.search(r"(?:FY|Annual)\s*[-_]?\s*(\d{4})", filename, re.IGNORECASE)
    if match:
        return f"FY-{match.group(1)}"

    return None


def load_documents_for_ticker(ticker: str, period: str | None = None) -> list[Document]:
    """
    Load all documents for a ticker.

    Args:
        ticker: Ticker symbol (e.g., "AMZN")
        period: Optional period filter. If None, extracts from filenames

    Returns:
        List of parsed documents
    """
    settings = get_settings(validate_llm=False)
    # Resolve to absolute path to avoid working directory issues
    # Try uppercase first, then lowercase (for flexibility)
    raw_dir_upper = settings.raw_dir.resolve() / ticker.upper()
    raw_dir_lower = settings.raw_dir.resolve() / ticker.lower()

    if raw_dir_upper.exists():
        raw_dir = raw_dir_upper
    elif raw_dir_lower.exists():
        raw_dir = raw_dir_lower
    else:
        raw_dir = raw_dir_upper  # Default for error message

    print(f"Looking for documents in: {raw_dir}")
    print(f"Directory exists: {raw_dir.exists()}")

    if not raw_dir.exists():
        print(f"WARNING: Directory {raw_dir} does not exist!")
        if settings.raw_dir.exists():
            print(f"Contents of {settings.raw_dir}:")
            for item in settings.raw_dir.iterdir():
                print(f"  - {item.name} ({'dir' if item.is_dir() else 'file'})")
        return []

    # List all files first
    all_files = list(raw_dir.iterdir())
    print(f"All files in directory: {len(all_files)}")
    for f in all_files:
        print(f"  - {f.name} (is_file: {f.is_file()}, suffix: {f.suffix})")

    docs: list[Document] = []

    # Process PDF files
    pdf_files = list(raw_dir.glob("*.pdf"))
    print(f"Found {len(pdf_files)} PDF files via glob")
    for path in pdf_files:
        source_metadata = load_sidecar(path)
        # Extract period from filename if not provided
        file_period = (
            period or source_metadata.get("period") or extract_period_from_filename(path.name)
        )

        if not file_period:
            print(f"  WARNING: Could not extract period from {path.name}, skipping")
            continue

        print(f"  Parsing: {path.name} (Period: {file_period})")
        try:
            doc = parse_pdf_to_document(
                path,
                doc_id=str(source_metadata.get("doc_id") or f"{ticker}_{file_period}_{path.stem}"),
                ticker=ticker,
                filing_type=str(source_metadata.get("filing_type") or "pdf"),
                period=file_period,
                source_url=source_metadata.get("source_url"),
                title=str(source_metadata.get("title") or path.stem),
            )
            apply_sidecar(doc, source_metadata)
            tag_sections(doc.blocks)
            print(f"    ✅ Created document with {len(doc.blocks)} blocks")
            docs.append(doc)
        except Exception as e:
            print(f"    ❌ ERROR parsing {path.name}: {e}")
            import traceback

            traceback.print_exc()

    # Process HTML files
    html_files = list(raw_dir.glob("*.html"))
    print(f"Found {len(html_files)} HTML files")
    for path in html_files:
        source_metadata = load_sidecar(path)
        # Extract period from filename if not provided
        file_period = (
            period or source_metadata.get("period") or extract_period_from_filename(path.name)
        )

        if not file_period:
            print(f"  WARNING: Could not extract period from {path.name}, skipping")
            continue

        print(f"  Parsing: {path.name} (Period: {file_period})")
        try:
            doc = parse_html_to_document(
                path,
                doc_id=str(source_metadata.get("doc_id") or f"{ticker}_{file_period}_{path.stem}"),
                ticker=ticker,
                filing_type=str(source_metadata.get("filing_type") or "html"),
                period=file_period,
                source_url=source_metadata.get("source_url"),
                title=str(source_metadata.get("title") or path.stem),
            )
            apply_sidecar(doc, source_metadata)
            tag_sections(doc.blocks)
            print(f"    ✅ Created document with {len(doc.blocks)} blocks")
            docs.append(doc)
        except Exception as e:
            print(f"    ❌ ERROR parsing {path.name}: {e}")
            import traceback

            traceback.print_exc()

    # Quartr transcript fileUrl objects are documented JSON, not PDFs.
    transcript_files = list(raw_dir.glob("*.json"))
    transcript_files = [
        path for path in transcript_files if not path.name.endswith(".metadata.json")
    ]
    print(f"Found {len(transcript_files)} transcript JSON files")
    for path in transcript_files:
        source_metadata = load_sidecar(path)
        if (
            source_metadata.get("source") != "quartr"
            or source_metadata.get("resource_kind") != "transcripts"
        ):
            continue
        file_period = period if period else str(source_metadata.get("period") or "")
        if not file_period:
            print(f"  WARNING: Missing period metadata for {path.name}, skipping")
            continue
        try:
            doc = parse_quartr_transcript_to_document(
                path,
                doc_id=str(source_metadata.get("doc_id") or f"{ticker}_{file_period}_{path.stem}"),
                ticker=ticker,
                filing_type=str(source_metadata.get("filing_type") or "transcript"),
                period=file_period,
                source_url=source_metadata.get("source_url"),
                title=str(source_metadata.get("title") or path.stem),
            )
            apply_sidecar(doc, source_metadata)
            tag_sections(doc.blocks)
            docs.append(doc)
        except Exception as e:
            print(f"    ERROR parsing {path.name}: {e}")
            import traceback

            traceback.print_exc()

    return docs


def discover_all_tickers() -> list[str]:
    """
    Auto-discover all ticker folders in data/raw/

    Returns:
        List of ticker symbols (folder names in uppercase)
    """
    settings = get_settings(validate_llm=False)
    raw_dir = settings.raw_dir.resolve()

    if not raw_dir.exists():
        print(f"ERROR: Raw data directory does not exist: {raw_dir}")
        return []

    tickers = []
    for item in raw_dir.iterdir():
        # Skip hidden files/folders and system files
        if (
            item.is_dir()
            and not item.name.startswith(".")
            and item.name.lower() not in [".ds_store"]
        ):
            tickers.append(item.name.upper())

    return sorted(tickers)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build vector index for financial documents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Index specific ticker and period
  python scripts/build_index.py --ticker AMZN --period Q3-2025
  
  # Index specific ticker (auto-detect periods from filenames)
  python scripts/build_index.py --ticker AMZN
  
  # Index multiple tickers with specific period
  python scripts/build_index.py --ticker AMZN --ticker AAPL --period Q3-2025
  
  # Index ALL companies (auto-discover from data/raw/ folders)
  python scripts/build_index.py --all
  
  # Index ALL companies for specific period
  python scripts/build_index.py --all --period Q3-2025
        """,
    )
    parser.add_argument(
        "--ticker",
        action="append",
        help="Ticker symbol (e.g., AMZN). Can be specified multiple times.",
    )
    parser.add_argument(
        "--period", help="Period identifier (e.g., Q3-2025). If omitted, extracts from filenames."
    )
    parser.add_argument(
        "--all", action="store_true", help="Process all tickers found in data/raw/ directory"
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Replace the Chroma collection before indexing to guarantee no stale chunks remain.",
    )
    args = parser.parse_args()

    # Determine which tickers to process
    if args.all:
        tickers = discover_all_tickers()
        if not tickers:
            print("ERROR: No ticker folders found in data/raw/")
            return
        print(f"🔍 Auto-discovered tickers: {', '.join(tickers)}")
    elif args.ticker:
        tickers = [t.upper() for t in args.ticker]
    else:
        print("ERROR: Must specify either --ticker or --all")
        parser.print_help()
        return

    print(f"\n{'=' * 60}")
    print(f"Building index for: {', '.join(tickers)}")
    if args.period:
        print(f"Period filter: {args.period}")
    else:
        print("Period: Auto-detect from filenames")
    print(f"{'=' * 60}\n")

    all_docs: list[Document] = []
    for ticker in tickers:
        print(f"\n📊 Processing {ticker}...")
        docs = load_documents_for_ticker(ticker, args.period)
        print(f"   Loaded {len(docs)} documents for {ticker}")
        all_docs.extend(docs)

    if not all_docs:
        print(
            "\n❌ ERROR: No documents found! Check that PDF/HTML files exist in data/raw/<TICKER>/"
        )
        print("\nExpected structure:")
        print("  data/raw/")
        print("  ├── AMZN/")
        print("  │   ├── Amazon - Q1 2025.pdf")
        print("  │   ├── Amazon - Q2 2025.pdf")
        print("  │   └── Amazon - Q3 2025.pdf")
        print("  └── AAPL/")
        print("      └── Apple - Q3 2025.pdf")
        return

    print(f"\n{'=' * 60}")
    print(f"✅ Total documents to index: {len(all_docs)}")
    print(f"{'=' * 60}\n")

    settings = get_settings(validate_llm=False)
    Path(settings.chroma_persist_dir).mkdir(parents=True, exist_ok=True)
    print(f"Indexing to: {settings.chroma_persist_dir}")

    try:
        index_documents(
            all_docs,
            persist_dir=settings.chroma_persist_dir,
            replace=args.fresh,
        )
        print("\n" + "=" * 60)
        print("🎉 Indexing completed successfully!")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ ERROR during indexing: {e}")
        import traceback

        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
