from datetime import UTC, datetime
from functools import lru_cache

from fastapi import APIRouter, HTTPException, status

from ...vectorstore.chroma_store import ChromaVectorStore
from ..dependencies import get_app_settings

router = APIRouter()


@lru_cache(maxsize=4)
def _get_health_store(persist_directory: str) -> ChromaVectorStore:
    return ChromaVectorStore(persist_directory=persist_directory)


def _timestamp_freshness(latest_fetch: object, max_age_hours: int) -> dict:
    if not latest_fetch:
        return {
            "status": "unknown",
            "latest_fetch": None,
            "age_hours": None,
            "max_age_hours": max_age_hours,
        }
    try:
        fetched_at = datetime.fromisoformat(str(latest_fetch).replace("Z", "+00:00"))
        age_hours = max(
            0.0,
            (datetime.now(UTC) - fetched_at.astimezone(UTC)).total_seconds() / 3600,
        )
    except ValueError:
        return {
            "status": "unknown",
            "latest_fetch": latest_fetch,
            "age_hours": None,
            "max_age_hours": max_age_hours,
        }
    return {
        "status": "fresh" if age_hours <= max_age_hours else "stale",
        "latest_fetch": latest_fetch,
        "age_hours": round(age_hours, 1),
        "max_age_hours": max_age_hours,
    }


def _freshness(stats: dict, max_age_hours: int) -> dict:
    ticker_latest_fetch = stats.get("ticker_latest_fetch")
    if not isinstance(ticker_latest_fetch, dict) or not ticker_latest_fetch:
        return _timestamp_freshness(stats.get("latest_fetch"), max_age_hours)

    by_ticker = {
        str(ticker).upper(): _timestamp_freshness(latest_fetch, max_age_hours)
        for ticker, latest_fetch in sorted(ticker_latest_fetch.items())
    }
    fresh_tickers = [ticker for ticker, value in by_ticker.items() if value["status"] == "fresh"]
    stale_tickers = [ticker for ticker, value in by_ticker.items() if value["status"] == "stale"]
    unknown_tickers = [
        ticker for ticker, value in by_ticker.items() if value["status"] == "unknown"
    ]
    if stale_tickers:
        corpus_status = "stale"
    elif unknown_tickers and fresh_tickers:
        corpus_status = "partial"
    elif unknown_tickers:
        corpus_status = "unknown"
    else:
        corpus_status = "fresh"

    known_ages = [
        float(value["age_hours"]) for value in by_ticker.values() if value["age_hours"] is not None
    ]
    return {
        "status": corpus_status,
        "latest_fetch": stats.get("latest_fetch"),
        "age_hours": max(known_ages) if known_ages else None,
        "max_age_hours": max_age_hours,
        "fresh_tickers": fresh_tickers,
        "stale_tickers": stale_tickers,
        "unknown_tickers": unknown_tickers,
        "by_ticker": by_ticker,
    }


@router.get("")
def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
def readiness() -> dict:
    """Confirm that required configuration and the packaged index are usable."""

    try:
        settings = get_app_settings()
        store = _get_health_store(str(settings.chroma_persist_dir))
        # Readiness is called repeatedly by the platform. Counting the collection
        # avoids the full metadata scan used by the detailed data-health route.
        chunk_count = store.count()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Backend dependencies are not ready.",
        ) from exc

    if chunk_count <= 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The financial document index is empty.",
        )
    return {
        "status": "ready",
        "index_chunks": chunk_count,
    }


@router.get("/data")
def data_health() -> dict:
    """Expose corpus provenance and age without leaking provider credentials."""

    try:
        settings = get_app_settings()
        store = _get_health_store(str(settings.chroma_persist_dir))
        stats = store.get_stats()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Corpus metadata is not available.",
        ) from exc
    return {
        "status": "ok",
        "quartr_source_present": "quartr" in stats["sources"],
        "freshness": _freshness(stats, settings.data_max_age_hours),
        "latest_source_update": stats["latest_source_update"],
        "sources": stats["sources"],
        "documents": stats["total_documents"],
        "chunks": stats["total_chunks"],
        "coverage": stats["ticker_period_map"],
    }
