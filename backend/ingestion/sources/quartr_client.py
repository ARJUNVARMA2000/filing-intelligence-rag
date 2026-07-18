from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

import httpx

ResourceKind = Literal["reports", "transcripts"]


class QuartrAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class QuartrResource:
    kind: ResourceKind
    id: int
    file_url: str
    type_id: int
    updated_at: str
    created_at: str
    company_id: int
    event_id: int
    event: dict[str, Any]

    @classmethod
    def from_api(cls, kind: ResourceKind, value: dict[str, Any]) -> QuartrResource:
        required = (
            "id",
            "fileUrl",
            "typeId",
            "updatedAt",
            "createdAt",
            "companyId",
            "eventId",
        )
        missing = [field for field in required if value.get(field) is None]
        if missing:
            raise QuartrAPIError(f"Quartr {kind} record is missing: {', '.join(missing)}")
        event = value.get("event")
        return cls(
            kind=kind,
            id=int(value["id"]),
            file_url=str(value["fileUrl"]),
            type_id=int(value["typeId"]),
            updated_at=str(value["updatedAt"]),
            created_at=str(value["createdAt"]),
            company_id=int(value["companyId"]),
            event_id=int(value["eventId"]),
            event=event if isinstance(event, dict) else {},
        )

    @property
    def period(self) -> str:
        fiscal_year = self.event.get("fiscalYear")
        fiscal_period = str(self.event.get("fiscalPeriod") or "").upper()
        if fiscal_year and fiscal_period:
            return f"{fiscal_period}-{fiscal_year}"
        if fiscal_year:
            return f"FY-{fiscal_year}"
        event_date = str(self.event.get("date") or "")
        return f"FY-{event_date[:4]}" if len(event_date) >= 4 else "UNDATED"


class QuartrClient:
    """Small client for the supported Quartr Public API v3 document endpoints."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.quartr.com/public/v3",
        timeout: float = 60.0,
        max_retries: int = 3,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError(
                "QUARTR_API_KEY is required. A Quartr web/Pro login is not an API credential."
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative.")
        self._max_retries = max_retries
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> QuartrClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key, "Accept": "application/json"}

    def _request(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> httpx.Response:
        headers = self._headers if authenticated else {"Accept": "*/*"}
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.get(url, headers=headers, params=params)
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise QuartrAPIError(f"Quartr request failed: {exc}") from exc
                time.sleep(min(2**attempt, 8))
                continue

            if response.status_code not in {429, 500, 502, 503, 504}:
                break
            if attempt >= self._max_retries:
                break
            retry_after = response.headers.get("Retry-After", "")
            try:
                delay = min(float(retry_after), 30.0)
            except ValueError:
                delay = min(2**attempt, 8)
            time.sleep(max(delay, 0.0))

        if response.status_code == 401:
            message = (
                "Quartr rejected the API key."
                if authenticated
                else "The Quartr file URL was not directly downloadable."
            )
            raise QuartrAPIError(message, status_code=401)
        if response.status_code == 403:
            message = (
                "Quartr API access is valid, but this dataset is not included in the subscription."
                if authenticated
                else "The Quartr file URL was not directly downloadable."
            )
            raise QuartrAPIError(message, status_code=403)
        if response.status_code == 429:
            raise QuartrAPIError("Quartr rate limit exceeded after retries.", status_code=429)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise QuartrAPIError(
                f"Quartr returned HTTP {response.status_code}.",
                status_code=response.status_code,
            ) from exc
        return response

    def iter_resources(
        self,
        kind: ResourceKind,
        *,
        tickers: Iterable[str],
        updated_after: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        type_ids: Iterable[int] | None = None,
        limit: int = 500,
    ) -> Iterable[QuartrResource]:
        if kind not in {"reports", "transcripts"}:
            raise ValueError(f"Unsupported Quartr resource kind: {kind}")
        if not 1 <= limit <= 500:
            raise ValueError("Quartr page limit must be between 1 and 500.")

        normalized_tickers = sorted(
            {ticker.strip().upper() for ticker in tickers if ticker.strip()}
        )
        if not normalized_tickers:
            raise ValueError("At least one ticker is required for Quartr synchronization.")

        cursor: int | None = 0
        seen_cursors: set[int] = set()
        while cursor is not None:
            if cursor in seen_cursors:
                raise QuartrAPIError("Quartr returned a repeated pagination cursor.")
            seen_cursors.add(cursor)
            params: dict[str, Any] = {
                "tickers": ",".join(normalized_tickers),
                "limit": limit,
                "cursor": cursor,
                "direction": "asc",
                "expand": "event",
            }
            if updated_after:
                params["updatedAfter"] = updated_after
            if start_date:
                params["startDate"] = start_date
            if end_date:
                params["endDate"] = end_date
            if type_ids:
                params["typeIds"] = ",".join(str(item) for item in type_ids)

            response = self._request(f"{self._base_url}/documents/{kind}", params=params)
            try:
                payload = response.json()
            except ValueError as exc:
                raise QuartrAPIError("Quartr returned a non-JSON list response.") from exc
            data = payload.get("data") if isinstance(payload, dict) else None
            pagination = payload.get("pagination") if isinstance(payload, dict) else None
            if not isinstance(data, list) or not isinstance(pagination, dict):
                raise QuartrAPIError("Quartr list response is missing data or pagination.")
            for item in data:
                if not isinstance(item, dict):
                    raise QuartrAPIError("Quartr list response contains an invalid record.")
                yield QuartrResource.from_api(kind, item)

            next_cursor = pagination.get("nextCursor")
            cursor = int(next_cursor) if next_cursor is not None else None

    def download(self, resource: QuartrResource) -> bytes:
        """Download the opaque fileUrl returned by Quartr without assuming a CDN shape."""

        # fileUrl is opaque and may be a signed CDN URL. Do not forward the API
        # key to another host; the Public API docs do not require it here.
        response = self._request(resource.file_url, authenticated=False)
        content = response.content
        if resource.kind == "reports" and not content.startswith(b"%PDF"):
            raise QuartrAPIError(f"Quartr report {resource.id} did not return a PDF.")
        if resource.kind == "transcripts":
            try:
                payload = response.json()
            except ValueError as exc:
                raise QuartrAPIError(
                    f"Quartr transcript {resource.id} did not return JSON."
                ) from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("transcript"), dict):
                raise QuartrAPIError(
                    f"Quartr transcript {resource.id} is missing the transcript object."
                )
        return content
