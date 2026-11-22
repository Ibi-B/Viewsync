"""Bounded TMDB title-detail and regional watch-provider enrichment.

The list snapshots remain the catalogue's discovery input. This module enriches
those same TMDB records in place, so no separate catalogue or client-side
ingestion path is created. Full detail and availability payloads are retained
with their catalogue item; a 30-day freshness window controls refresh attempts,
not deletion of information already used by the published catalogue.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin

import requests

TMDB_BASE = "https://api.themoviedb.org/3/"
DETAIL_CACHE_MAX_AGE = timedelta(days=30)
REQUEST_TIMEOUT_SECONDS = 15
MAX_WORKERS = 3
MAX_RETRIES = 2
MAX_RETRY_DELAY_SECONDS = 30


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _credentials() -> tuple[str | None, str | None]:
    key = os.environ.get("TMDB_API_KEY", "").strip() or None
    token = os.environ.get("TMDB_ACCESS_TOKEN", "").strip() or None
    return key, token


def _retry_delay(response: requests.Response | None, attempt: int) -> float:
    raw = response.headers.get("Retry-After", "").strip() if response is not None else ""
    delay: float | None = None
    try:
        delay = max(0.0, float(raw))
    except (TypeError, ValueError):
        if raw:
            try:
                delay = max(
                    0.0,
                    (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds(),
                )
            except (TypeError, ValueError, OverflowError):
                delay = None
    if delay is None:
        delay = float(2 ** attempt)
    return min(delay, float(MAX_RETRY_DELAY_SECONDS))


def _request_json(path: str, params: dict[str, Any] | None = None) -> Any:
    api_key, access_token = _credentials()
    if not api_key and not access_token:
        raise RuntimeError("TMDB credentials are not configured")
    query = dict(params or {})
    headers = {"Accept": "application/json", "User-Agent": "Viewsync/1.0"}
    if api_key:
        query["api_key"] = api_key
    elif access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    url = urljoin(TMDB_BASE, path.lstrip("/"))
    for attempt in range(MAX_RETRIES + 1):
        response = requests.get(
            url,
            params=query,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < MAX_RETRIES:
                time.sleep(_retry_delay(response, attempt))
                continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError("TMDB request retry limit reached")


def _fetch_item(media_type: str, tmdb_id: int, fetched_at: str) -> dict[str, Any]:
    namespace = "movie" if media_type == "movie" else "tv"
    appended = (
        "credits,external_ids,images,keywords,recommendations,release_dates,videos"
        if media_type == "movie"
        else "aggregate_credits,content_ratings,external_ids,images,keywords,recommendations,videos"
    )
    details = _request_json(
        f"{namespace}/{tmdb_id}",
        {"language": "en-US", "append_to_response": appended},
    )
    provider_payload = _request_json(f"{namespace}/{tmdb_id}/watch/providers")
    provider_regions = provider_payload.get("results", {}) if isinstance(provider_payload, dict) else {}
    if not isinstance(provider_regions, dict):
        provider_regions = {}
    return {
        "fetched_at": fetched_at,
        "status": "fresh",
        "details": details if isinstance(details, dict) else {},
        "watch_providers": provider_regions,
        "watch_providers_response": (
            provider_payload if isinstance(provider_payload, dict) else {}
        ),
    }


def _is_fresh(record: Any, now: datetime) -> bool:
    if not isinstance(record, dict):
        return False
    fetched_at = _parse_time(record.get("fetched_at"))
    return fetched_at is not None and timedelta(0) <= now - fetched_at < DETAIL_CACHE_MAX_AGE


def _current_cache(snapshots: list[Any]) -> dict[tuple[str, str], dict[str, Any]]:
    cache: dict[tuple[str, str], dict[str, Any]] = {}
    for snapshot in snapshots:
        if snapshot.provider_id != "tmdb" or snapshot.media_type not in {"movie", "series"}:
            continue
        for item in snapshot.items:
            if not isinstance(item, dict):
                continue
            tmdb_id = item.get("id")
            record = item.get("tmdb_enrichment")
            if tmdb_id is None or not isinstance(record, dict):
                continue
            key = (snapshot.media_type, str(tmdb_id))
            current = cache.get(key)
            current_time = _parse_time(record.get("fetched_at"))
            prior_time = _parse_time(current.get("fetched_at")) if current else None
            if current is None or (current_time and (prior_time is None or current_time > prior_time)):
                cache[key] = record
    return cache


def _watch_regions() -> list[dict[str, str]]:
    payload = _request_json("configuration/countries", {"language": "en-US"})
    if not isinstance(payload, list):
        return []
    result = []
    seen = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        code = str(item.get("iso_3166_1") or "").strip().upper()
        name = str(item.get("english_name") or item.get("native_name") or "").strip()
        if len(code) != 2 or not name or code in seen:
            continue
        seen.add(code)
        result.append({
            "iso_code": code,
            "english_name": name,
            "native_name": str(item.get("native_name") or name),
        })
    return sorted(result, key=lambda row: row["english_name"].casefold())


def enrich_tmdb_snapshots(
    snapshots: list[Any],
    now: datetime | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Attach rich TMDB details and provider availability to every distinct TMDB title."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    fetched_at = now.isoformat()
    cache = _current_cache(snapshots)
    requested: dict[tuple[str, str], None] = {}
    item_refs: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for snapshot in snapshots:
        if snapshot.provider_id != "tmdb" or snapshot.media_type not in {"movie", "series"}:
            continue
        for item in snapshot.items:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            key = (snapshot.media_type, str(item["id"]))
            requested[key] = None
            item_refs.setdefault(key, []).append(item)

    refresh = [key for key in requested if not _is_fresh(cache.get(key), now)]
    fetched = 0
    failures = 0
    if refresh and (_credentials()[0] or _credentials()[1]):
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {
                pool.submit(_fetch_item, media_type, int(tmdb_id), fetched_at): (media_type, tmdb_id)
                for media_type, tmdb_id in refresh
                if tmdb_id.isdigit()
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    cache[key] = future.result()
                    fetched += 1
                except Exception:
                    failures += 1
                    stale = cache.get(key)
                    if isinstance(stale, dict):
                        retained = dict(stale)
                        retained["status"] = "stale"
                        cache[key] = retained

    for key, refs in item_refs.items():
        record = cache.get(key)
        if not isinstance(record, dict):
            continue
        for item in refs:
            item["tmdb_enrichment"] = record

    try:
        regions = _watch_regions() if (_credentials()[0] or _credentials()[1]) else []
    except Exception:
        regions = []

    return regions, {
        "unique_tmdb_titles": len(requested),
        "detail_refresh_candidates": len(refresh),
        "detail_titles_refreshed": fetched,
        "detail_refresh_failures": failures,
        "cached_titles_reused": len(requested) - len(refresh),
        "regions_published": len(regions),
        "cache_freshness_days": int(DETAIL_CACHE_MAX_AGE.total_seconds() // 86400),
        "provider_availability": "TMDB watch/providers by region",
    }
