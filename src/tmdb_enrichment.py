"""TMDB enrichment and provider-specific regional discovery for Viewsync.

The durable Git state branch contains source-list snapshots only. Full TMDB
metadata lives in the currently published per-item detail documents; the next
generation may reuse those documents while they are fresh, but they are never
copied into append-only Git history. Details and watch availability have
separate refresh windows and a hard cache age below TMDB's six-month limit.
"""
from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin

import requests

TMDB_BASE = "https://api.themoviedb.org/3/"
PUBLIC_CATALOGUE_BASE = os.environ.get(
    "VIEWSYNC_PUBLIC_BASE", "https://ibi-b.github.io/Viewsync"
).rstrip("/")
DETAIL_REFRESH_AGE = timedelta(days=30)
AVAILABILITY_REFRESH_AGE = timedelta(hours=12)
DETAIL_HARD_MAX_AGE = timedelta(days=150)
AVAILABILITY_STALE_GRACE = timedelta(days=150)
REQUEST_TIMEOUT_SECONDS = 15
PUBLIC_CACHE_TIMEOUT_SECONDS = 10
MAX_WORKERS = 4
MAX_CACHE_WORKERS = 10
MAX_RETRIES = 2
MAX_RETRY_DELAY_SECONDS = 30
MAX_PUBLIC_JSON_BYTES = 4 * 1024 * 1024
MAX_DISCOVER_PAGES = 2
MIN_SHELF_ITEMS = 5
SHELF_ITEM_LIMIT = 10

# Regions intentionally provisioned for regional shelves. Add supported ISO
# 3166-1 codes through the TMDB_WATCH_REGIONS Actions variable. We intersect
# this configured set with TMDB's watch-provider region endpoint.
DEFAULT_WATCH_REGIONS = (
    "SE", "GB", "US", "CA", "AU", "DE", "FR", "NL"
)

PROVIDER_ALLOWLIST: dict[str, dict[str, Any]] = {
    "netflix": {
        "display_name": "Netflix",
        "aliases": {"netflix"},
    },
    "prime-video": {
        "display_name": "Prime Video",
        "aliases": {"amazon prime video", "prime video"},
    },
    "disney-plus": {
        "display_name": "Disney+",
        "aliases": {"disney+", "disney plus"},
    },
    "apple-tv": {
        "display_name": "Apple TV",
        "aliases": {"apple tv", "apple tv+", "apple tv plus"},
    },
    "max": {
        "display_name": "Max",
        "aliases": {"max", "hbo max"},
    },
    "skyshowtime": {
        "display_name": "SkyShowtime",
        "aliases": {"skyshowtime"},
    },
}


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


def _age(value: Any, now: datetime) -> timedelta | None:
    timestamp = _parse_time(value)
    if timestamp is None:
        return None
    age = now - timestamp
    return age if age >= timedelta(0) else None


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
                    (
                        parsedate_to_datetime(raw) - datetime.now(timezone.utc)
                    ).total_seconds(),
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


def _safe_failure(error: Exception) -> str:
    response = getattr(error, "response", None)
    if response is not None:
        return f"HTTP {response.status_code}"
    return type(error).__name__


def _normalise_provider(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _provider_service(provider_name: str) -> str | None:
    normalized = _normalise_provider(provider_name)
    for key, config in PROVIDER_ALLOWLIST.items():
        aliases = {_normalise_provider(alias) for alias in config["aliases"]}
        if normalized in aliases:
            return key
    return None


def _configured_regions() -> list[str]:
    raw = os.environ.get("TMDB_WATCH_REGIONS", "")
    values = raw.split(",") if raw.strip() else list(DEFAULT_WATCH_REGIONS)
    result: list[str] = []
    for value in values:
        code = str(value).strip().upper()
        if re.fullmatch(r"[A-Z]{2}", code) and code not in result:
            result.append(code)
    return result


def _watch_regions() -> list[dict[str, str]]:
    payload = _request_json("watch/providers/regions", {"language": "en-US"})
    results = payload.get("results", []) if isinstance(payload, dict) else []
    configured = set(_configured_regions())
    regions: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("iso_3166_1") or "").strip().upper()
        name = str(item.get("english_name") or item.get("native_name") or "").strip()
        if code not in configured or code in seen or not name:
            continue
        seen.add(code)
        regions.append({
            "iso_code": code,
            "english_name": name,
            "native_name": str(item.get("native_name") or name),
        })
    # The region list is an explicit configured coverage boundary. Do not
    # silently fall back to configuration/countries, which includes markets
    # without watch-provider data.
    return regions


def _provider_catalogue(region: str, media_type: str) -> list[dict[str, Any]]:
    endpoint = "watch/providers/movie" if media_type == "movie" else "watch/providers/tv"
    payload = _request_json(endpoint, {"language": "en-US", "watch_region": region})
    results = payload.get("results", []) if isinstance(payload, dict) else []
    return [row for row in results if isinstance(row, dict)] if isinstance(results, list) else []


def _discover_provider(
    media_type: str,
    region: str,
    provider_id: int,
) -> list[dict[str, Any]]:
    endpoint = "discover/movie" if media_type == "movie" else "discover/tv"
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, MAX_DISCOVER_PAGES + 1):
        payload = _request_json(
            endpoint,
            {
                "language": "en-US",
                "include_adult": "false",
                "watch_region": region,
                "with_watch_providers": str(provider_id),
                "with_watch_monetization_types": "flatrate",
                "sort_by": "popularity.desc",
                "page": page,
            },
        )
        page_results = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(page_results, list):
            break
        for item in page_results:
            if not isinstance(item, dict):
                continue
            tmdb_id = item.get("id")
            # Vote count is confidence metadata, never a discovery eligibility gate.
            if tmdb_id is None:
                continue
            key = str(tmdb_id)
            if key in seen:
                continue
            seen.add(key)
            results.append(item)
            if len(results) >= SHELF_ITEM_LIMIT:
                break
        if len(results) >= SHELF_ITEM_LIMIT:
            break
        if page_results and len(page_results) < 20:
            break
    return results[:SHELF_ITEM_LIMIT]


def _load_cached_provider_shelves(
    region: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]] | None:
    """Reuse a published regional ranking while it is inside the 12h SLA."""
    code = str(region.get("iso_code") or "").upper()
    path = region.get("provider_shelves_path")
    if not code or not path:
        return None
    try:
        payload = _public_json(PUBLIC_CATALOGUE_BASE, str(path))
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("region") != code:
        return None
    cached_shelves = payload.get("shelves")
    if not isinstance(cached_shelves, list):
        return None
    result: list[dict[str, Any]] = []
    for shelf in cached_shelves:
        if not isinstance(shelf, dict):
            continue
        items = shelf.get("items")
        if not isinstance(items, list):
            continue
        result.append({
            key: value for key, value in shelf.items() if key != "items"
        } | {"items": [dict(item) for item in items if isinstance(item, dict)]})
    if not result:
        return None
    return result


def _load_previous_region_directory(
    base_url: str = PUBLIC_CATALOGUE_BASE,
) -> dict[str, dict[str, Any]]:
    try:
        manifest = _public_json(base_url, "manifest.json")
    except Exception:
        return {}
    regions = manifest.get("watch_regions", []) if isinstance(manifest, dict) else []
    return {
        str(row.get("iso_code") or "").upper(): row
        for row in regions
        if isinstance(row, dict) and row.get("iso_code")
    }


def discover_provider_shelves(
    now: datetime | None = None,
) -> tuple[
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[tuple[str, str], dict[str, Any]],
    dict[str, Any],
]:
    """Discover allowlisted services per configured region and media type."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    fetched_at = now.isoformat()
    if not any(_credentials()):
        # Credential removal/outage must not immediately blank provider shelves.
        # Reuse the last published regional documents as stale, but never beyond
        # the same 150-day hard cache ceiling used for per-item availability.
        previous_regions = _load_previous_region_directory()
        cached_regions: list[dict[str, Any]] = []
        shelves_by_region: dict[str, list[dict[str, Any]]] = {}
        discovered: dict[tuple[str, str], dict[str, Any]] = {}
        expired_shelves = 0
        for code, previous_region in previous_regions.items():
            age = _age(previous_region.get("availability_updated_at"), now)
            if age is None or age >= AVAILABILITY_STALE_GRACE:
                expired_shelves += 1
                continue
            cached_shelves = _load_cached_provider_shelves(previous_region, now)
            if not cached_shelves:
                continue
            if age >= AVAILABILITY_REFRESH_AGE:
                for shelf in cached_shelves:
                    shelf["availability_status"] = "stale"
            shelves_by_region[code] = cached_shelves
            cached_regions.append({
                "iso_code": code,
                "english_name": str(previous_region.get("english_name") or code),
                "native_name": str(previous_region.get("native_name") or code),
                "availability_updated_at": previous_region.get("availability_updated_at"),
            })
            for shelf in cached_shelves:
                media_kind = str(shelf.get("media_kind") or "")
                for item in shelf.get("items", []):
                    tmdb_id = str(item.get("tmdb_id") or "")
                    if not tmdb_id:
                        continue
                    images = item.get("images")
                    images = images if isinstance(images, dict) else {}
                    discovered.setdefault((media_kind, tmdb_id), {
                        "id": int(tmdb_id) if tmdb_id.isdigit() else tmdb_id,
                        "tmdb_id": tmdb_id,
                        "media_type": media_kind,
                        "title": item.get("title") or "",
                        "release_date": item.get("release_date"),
                        "popularity": item.get("popularity"),
                        "vote_average": item.get("rating"),
                        "vote_count": item.get("vote_count"),
                        "poster_path": images.get("poster"),
                        "backdrop_path": images.get("backdrop"),
                    })
        return cached_regions, shelves_by_region, discovered, {
            "configured_region_count": len(previous_regions),
            "published_region_count": len(cached_regions),
            "provider_catalogue_requests": 0,
            "provider_discover_requests": 0,
            "provider_shelf_regions_reused": len(cached_regions),
            "provider_shelves_expired": expired_shelves,
            "provider_shelves_published": sum(
                len(shelves) for shelves in shelves_by_region.values()
            ),
            "provider_shelves_omitted_under_minimum": 0,
            "provider_discovery_errors": [],
            "provider_allowlist": sorted(PROVIDER_ALLOWLIST),
            "availability_refresh_hours": int(
                AVAILABILITY_REFRESH_AGE.total_seconds() // 3600
            ),
            "skipped_reason": "TMDB credentials are not configured; retained valid cached shelves",
        }

    previous_regions = _load_previous_region_directory()
    try:
        regions = _watch_regions()
    except Exception as exc:
        # Provider endpoint outages must not wipe the previous region list.
        # Existing shelves can still be reused with an explicit stale marker.
        regions = [
            {
                "iso_code": code,
                "english_name": str(value.get("english_name") or code),
                "native_name": str(value.get("native_name") or code),
            }
            for code, value in previous_regions.items()
        ]
        region_directory_error = _safe_failure(exc)
    else:
        region_directory_error = None
        if not regions and previous_regions:
            # An unexpectedly empty success is not evidence that every
            # previously supported market disappeared. Retain the last-good
            # configured directory and let per-market shelf refresh/status
            # determine what remains usable.
            regions = [
                {
                    "iso_code": code,
                    "english_name": str(value.get("english_name") or code),
                    "native_name": str(value.get("native_name") or code),
                }
                for code, value in previous_regions.items()
            ]
            region_directory_error = (
                "Empty TMDB watch-provider region response; retained last-good directory"
            )
    shelves_by_region: dict[str, list[dict[str, Any]]] = {}
    discovered: dict[tuple[str, str], dict[str, Any]] = {}
    provider_calls = 0
    discover_calls = 0
    cached_regions = 0
    expired_provider_shelves = 0
    omitted_under_minimum = 0
    errors: list[dict[str, str]] = []
    if region_directory_error:
        errors.append({
            "stage": "region_directory",
            "error": region_directory_error,
        })

    for region in regions:
        region_code = region["iso_code"]
        previous_region = previous_regions.get(region_code, {})
        previous_age = _age(previous_region.get("availability_updated_at"), now)
        cached_shelves = _load_cached_provider_shelves(previous_region, now)

        def retain_cached(media_type: str, service_key: str | None = None) -> None:
            nonlocal expired_provider_shelves
            for old_shelf in cached_shelves or []:
                if old_shelf.get("media_kind") != media_type:
                    continue
                if service_key is not None and old_shelf.get("service_key") != service_key:
                    continue
                shelf_age = _age(old_shelf.get("availability_updated_at"), now)
                if shelf_age is None or shelf_age >= AVAILABILITY_STALE_GRACE:
                    # Do not republish old TMDB-derived shelf summaries once
                    # their hard cache-age boundary has been reached.
                    expired_provider_shelves += 1
                    continue
                retained = dict(old_shelf)
                retained["availability_status"] = "stale"
                shelves.append(retained)
                for shelf_item in retained.get("items", []):
                    tmdb_id = str(shelf_item.get("tmdb_id") or "")
                    if not tmdb_id:
                        continue
                    images = shelf_item.get("images")
                    images = images if isinstance(images, dict) else {}
                    candidate = {
                        "id": int(tmdb_id) if tmdb_id.isdigit() else tmdb_id,
                        "tmdb_id": tmdb_id,
                        "media_type": media_type,
                        "title": shelf_item.get("title") or "",
                        "release_date": shelf_item.get("release_date"),
                        "popularity": shelf_item.get("popularity"),
                        "vote_average": shelf_item.get("rating"),
                        "vote_count": shelf_item.get("vote_count"),
                        "poster_path": images.get("poster"),
                        "backdrop_path": images.get("backdrop"),
                    }
                    discovered.setdefault((media_type, tmdb_id), candidate)

        if previous_age is not None and previous_age < AVAILABILITY_REFRESH_AGE and cached_shelves:
            shelves_by_region[region_code] = cached_shelves
            cached_regions += 1
            for shelf in cached_shelves:
                media_type = str(shelf.get("media_kind") or "")
                for item in shelf.get("items", []):
                    tmdb_id = str(item.get("tmdb_id") or "")
                    if not tmdb_id:
                        continue
                    images = item.get("images")
                    images = images if isinstance(images, dict) else {}
                    candidate = {
                        "id": int(tmdb_id) if tmdb_id.isdigit() else tmdb_id,
                        "tmdb_id": tmdb_id,
                        "media_type": media_type,
                        "title": item.get("title") or "",
                        "release_date": item.get("release_date"),
                        "popularity": item.get("popularity"),
                        "vote_average": item.get("rating"),
                        "vote_count": item.get("vote_count"),
                        "poster_path": images.get("poster"),
                        "backdrop_path": images.get("backdrop"),
                    }
                    discovered.setdefault((media_type, tmdb_id), candidate)
            continue

        shelves: list[dict[str, Any]] = []
        for media_type in ("movie", "series"):
            try:
                provider_rows = _provider_catalogue(region_code, media_type)
                provider_calls += 1
            except Exception as exc:
                errors.append({
                    "region": region_code,
                    "media_type": media_type,
                    "stage": "provider_catalogue",
                    "error": _safe_failure(exc),
                })
                retain_cached(media_type)
                continue

            selected: dict[str, dict[str, Any]] = {}
            for provider in provider_rows:
                service_key = _provider_service(provider.get("provider_name"))
                provider_id = provider.get("provider_id")
                if service_key is None or not isinstance(provider_id, int) or provider_id <= 0:
                    continue
                current = selected.get(service_key)
                priority = provider.get("display_priority")
                current_priority = current.get("display_priority") if current else None
                if current is None or (
                    isinstance(priority, int)
                    and (not isinstance(current_priority, int) or priority < current_priority)
                ):
                    selected[service_key] = provider

            for service_key, provider in selected.items():
                try:
                    provider_id = int(provider["provider_id"])
                    items = _discover_provider(media_type, region_code, provider_id)
                    discover_calls += 1
                except Exception as exc:
                    errors.append({
                        "region": region_code,
                        "media_type": media_type,
                        "provider": service_key,
                        "stage": "discover",
                        "error": _safe_failure(exc),
                    })
                    retain_cached(media_type, service_key)
                    continue

                if len(items) < MIN_SHELF_ITEMS:
                    omitted_under_minimum += 1
                    # This is a successful current result, so an older larger
                    # shelf is not retained when it no longer meets the rule.
                    continue

                service = PROVIDER_ALLOWLIST[service_key]
                label = (
                    f"Top 10 on {service['display_name']}"
                    if len(items) >= SHELF_ITEM_LIMIT
                    else f"Popular on {service['display_name']}"
                )
                logo_path = str(provider.get("logo_path") or "").strip()
                logo_url = (
                    f"https://image.tmdb.org/t/p/w92{logo_path}"
                    if logo_path.startswith("/")
                    else None
                )
                shelf_items: list[dict[str, Any]] = []
                for rank, raw_item in enumerate(items, start=1):
                    tmdb_id = str(raw_item["id"])
                    key = (media_type, tmdb_id)
                    candidate = dict(raw_item)
                    candidate["media_type"] = media_type
                    candidate["tmdb_id"] = tmdb_id
                    candidate["provider_rank"] = rank
                    discovered.setdefault(key, candidate)
                    date_value = (
                        candidate.get("release_date")
                        if media_type == "movie"
                        else candidate.get("first_air_date")
                    )
                    shelf_items.append({
                        "id": f"{media_type}:tmdb:{tmdb_id}",
                        "tmdb_id": tmdb_id,
                        "media_kind": media_type,
                        "title": str(
                            candidate.get("title") or candidate.get("name") or ""
                        ),
                        "year": str(date_value or "")[:4] or None,
                        "release_date": date_value,
                        "images": {
                            "poster": _image_url(candidate.get("poster_path"), "w500"),
                            "backdrop": _image_url(candidate.get("backdrop_path"), "w1280"),
                        },
                        "popularity": candidate.get("popularity"),
                        "rating": candidate.get("vote_average"),
                        "vote_count": candidate.get("vote_count"),
                        "rank": rank,
                    })

                shelves.append({
                    "id": f"{service_key}:{media_type}",
                    "service_key": service_key,
                    "provider_id": provider_id,
                    "provider_name": service["display_name"],
                    "provider_logo": logo_url,
                    "media_kind": media_type,
                    "title": label,
                    "display_mode": "top_10" if len(items) >= SHELF_ITEM_LIMIT else "popular",
                    "availability_status": "fresh",
                    "items": shelf_items,
                    "availability_updated_at": fetched_at,
                })
        if shelves:
            shelves_by_region[region_code] = shelves

    published_regions = []
    for region in regions:
        region_shelves = shelves_by_region.get(region["iso_code"], [])
        if not region_shelves:
            continue
        # Use the oldest contributing shelf timestamp so the region badge
        # never presents partially refreshed provider data as wholly current.
        shelf_times = [
            _parse_time(shelf.get("availability_updated_at"))
            for shelf in region_shelves
        ]
        valid_times = [value for value in shelf_times if value is not None]
        region_updated = min(valid_times).isoformat() if valid_times else fetched_at
        published_regions.append({
            **region,
            "availability_updated_at": region_updated,
        })
    report = {
        "configured_region_count": len(regions),
        "published_region_count": len(published_regions),
        "provider_catalogue_requests": provider_calls,
        "provider_discover_requests": discover_calls,
        "provider_shelf_regions_reused": cached_regions,
        "provider_shelves_expired": expired_provider_shelves,
        "provider_shelves_published": sum(len(rows) for rows in shelves_by_region.values()),
        "provider_shelves_omitted_under_minimum": omitted_under_minimum,
        "provider_discovery_errors": errors,
        "provider_allowlist": sorted(PROVIDER_ALLOWLIST),
        "availability_refresh_hours": int(AVAILABILITY_REFRESH_AGE.total_seconds() // 3600),
    }
    return published_regions, shelves_by_region, discovered, report


def _image_url(value: Any, size: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = value.strip()
    if path.startswith(("https://", "http://")):
        return path
    if path.startswith("/") and not path.startswith("//"):
        return f"https://image.tmdb.org/t/p/{size}{path}"
    return None


def _public_url(base_url: str, relative_path: str) -> str:
    base = base_url.rstrip("/") + "/"
    clean = relative_path.lstrip("/")
    if clean.startswith("v1/"):
        clean = clean[3:]
    return urljoin(base + "v1/", clean)


def _public_json(base_url: str, relative_path: str) -> Any:
    response = requests.get(
        _public_url(base_url, relative_path),
        headers={"Accept": "application/json", "User-Agent": "Viewsync/1.0"},
        timeout=PUBLIC_CACHE_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    if len(response.content) > MAX_PUBLIC_JSON_BYTES:
        raise ValueError("Previous published catalogue document exceeded the cache size limit")
    return response.json()


def load_previous_detail_index(
    base_url: str = PUBLIC_CATALOGUE_BASE,
    regions: list[dict[str, Any]] | None = None,
) -> dict[tuple[str, str], str]:
    """Index current published per-item documents without persisting TMDB data in Git."""
    try:
        manifest = _public_json(base_url, "manifest.json")
    except Exception:
        return {}
    if not isinstance(manifest, dict):
        return {}

    index: dict[tuple[str, str], str] = {}

    def add_item(item: Any) -> None:
        if not isinstance(item, dict):
            return
        tmdb_id = item.get("tmdb_id")
        media_type = item.get("media_kind") or item.get("media_type")
        details_path = item.get("details_path")
        if tmdb_id is None and isinstance(item.get("ids"), dict):
            tmdb_id = item["ids"].get("tmdb")
        if tmdb_id is None or media_type not in {"movie", "series"}:
            return
        if isinstance(details_path, str) and details_path:
            index[(str(media_type), str(tmdb_id))] = details_path

    for row_ref in manifest.get("rows", []):
        if not isinstance(row_ref, dict) or not row_ref.get("path"):
            continue
        try:
            row = _public_json(base_url, str(row_ref["path"]))
        except Exception:
            continue
        if isinstance(row, dict):
            for item in row.get("items", []):
                add_item(item)

    selected_codes = {
        str(region.get("iso_code") or "").upper()
        for region in (regions or manifest.get("watch_regions", []))
        if isinstance(region, dict)
    }
    for region in manifest.get("watch_regions", []):
        if not isinstance(region, dict):
            continue
        code = str(region.get("iso_code") or "").upper()
        path = region.get("provider_shelves_path")
        if code not in selected_codes or not path:
            continue
        try:
            payload = _public_json(base_url, str(path))
        except Exception:
            continue
        if isinstance(payload, dict):
            for shelf in payload.get("shelves", []):
                if isinstance(shelf, dict):
                    for item in shelf.get("items", []):
                        add_item(item)
    return index


def _load_previous_item(
    key: tuple[str, str],
    detail_index: dict[tuple[str, str], str],
    base_url: str,
) -> dict[str, Any] | None:
    path = detail_index.get(key)
    if not path:
        return None
    try:
        payload = _public_json(base_url, path)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _fetch_details(media_type: str, tmdb_id: str) -> dict[str, Any]:
    namespace = "movie" if media_type == "movie" else "tv"
    appended = (
        "alternative_titles,credits,external_ids,images,keywords,recommendations,release_dates,reviews,similar,translations,videos"
        if media_type == "movie"
        else "aggregate_credits,alternative_titles,content_ratings,credits,episode_groups,external_ids,images,keywords,recommendations,reviews,similar,translations,videos"
    )
    payload = _request_json(
        f"{namespace}/{tmdb_id}",
        {"language": "en-US", "append_to_response": appended},
    )
    if not isinstance(payload, dict):
        raise ValueError("TMDB detail response was not an object")
    return payload


def _fetch_watch_providers(media_type: str, tmdb_id: str) -> dict[str, Any]:
    namespace = "movie" if media_type == "movie" else "tv"
    payload = _request_json(f"{namespace}/{tmdb_id}/watch/providers")
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), dict):
        raise ValueError("TMDB watch-provider response was invalid")
    return payload["results"]


def _tmdb_identity_aliases(details: Any) -> dict[str, str]:
    if not isinstance(details, dict):
        return {}
    external_ids = details.get("external_ids")
    if not isinstance(external_ids, dict):
        return {}
    aliases = {
        "imdb": "imdb_id",
        "tmdb": "id",
        "tvdb": "tvdb_id",
        "tvmaze": "tvmaze_id",
        "wikidata": "wikidata_id",
    }
    result: dict[str, str] = {}
    for alias, source_key in aliases.items():
        value = details.get("id") if source_key == "id" else external_ids.get(source_key)
        if value not in (None, ""):
            result[alias] = str(value)
    return result


def _refresh_record(
    key: tuple[str, str],
    previous: dict[str, Any] | None,
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    media_type, tmdb_id = key
    details = previous.get("tmdb_full") if previous else None
    providers = previous.get("watch_providers") if previous else None
    details_at = previous.get("tmdb_details_fetched_at") if previous else None
    providers_at = previous.get("tmdb_watch_providers_fetched_at") if previous else None
    ids = {
        str(name): str(value)
        for name, value in (previous.get("ids", {}) if previous else {}).items()
        if value not in (None, "")
    }
    ids.setdefault("tmdb", str(tmdb_id))
    if isinstance(details, dict):
        ids.update(_tmdb_identity_aliases(details))
    errors: list[dict[str, str]] = []

    details_age = _age(details_at, now)
    if (
        not isinstance(details, dict)
        or not details
        or details_age is None
        or details_age >= DETAIL_REFRESH_AGE
    ):
        try:
            details = _fetch_details(media_type, tmdb_id)
            details_at = now.isoformat()
            detail_status = "fresh"
            ids.update(_tmdb_identity_aliases(details))
        except Exception as exc:
            if isinstance(details, dict) and details and details_age is not None:
                if details_age < DETAIL_HARD_MAX_AGE:
                    detail_status = "stale"
                    errors.append({
                        "media_kind": media_type,
                        "tmdb_id": tmdb_id,
                        "stage": "details_refresh",
                        "error": _safe_failure(exc),
                    })
                else:
                    # Descriptive TMDB metadata is purged at the hard age
                    # boundary, but stable identifiers remain available.
                    details = {}
                    detail_status = "expired"
                    errors.append({
                        "media_kind": media_type,
                        "tmdb_id": tmdb_id,
                        "stage": "details_cache_expired",
                        "error": _safe_failure(exc),
                    })
            elif isinstance(details, dict) and details:
                # Unknown-age metadata cannot safely be retained under the
                # documented cache ceiling.
                details = {}
                detail_status = "expired"
                errors.append({
                    "media_kind": media_type,
                    "tmdb_id": tmdb_id,
                    "stage": "details_cache_expired",
                    "error": _safe_failure(exc),
                })
            else:
                # A first-time enrichment failure is non-fatal. The slim
                # catalogue/shelf item remains publishable and will retry
                # because it has no successful fetched-at timestamp.
                details = {}
                details_at = None
                detail_status = "unavailable"
                errors.append({
                    "media_kind": media_type,
                    "tmdb_id": tmdb_id,
                    "stage": "details_unavailable",
                    "error": _safe_failure(exc),
                })
    else:
        detail_status = str(previous.get("tmdb_details_status") or "fresh")

    providers_age = _age(providers_at, now)
    if (
        not isinstance(providers, dict)
        or not providers
        or providers_age is None
        or providers_age >= AVAILABILITY_REFRESH_AGE
    ):
        try:
            providers = _fetch_watch_providers(media_type, tmdb_id)
            providers_at = now.isoformat()
            availability_status = "fresh"
        except Exception as exc:
            if isinstance(providers, dict) and providers and providers_age is not None:
                if providers_age < AVAILABILITY_STALE_GRACE:
                    availability_status = "stale"
                    errors.append({
                        "media_kind": media_type,
                        "tmdb_id": tmdb_id,
                        "stage": "availability_refresh",
                        "error": _safe_failure(exc),
                    })
                else:
                    providers = {}
                    availability_status = "expired"
                    errors.append({
                        "media_kind": media_type,
                        "tmdb_id": tmdb_id,
                        "stage": "availability_cache_expired",
                        "error": _safe_failure(exc),
                    })
            elif isinstance(providers, dict) and providers:
                providers = {}
                availability_status = "expired"
                errors.append({
                    "media_kind": media_type,
                    "tmdb_id": tmdb_id,
                    "stage": "availability_cache_expired",
                    "error": _safe_failure(exc),
                })
            else:
                providers = {}
                providers_at = None
                availability_status = "unavailable"
                errors.append({
                    "media_kind": media_type,
                    "tmdb_id": tmdb_id,
                    "stage": "availability_unavailable",
                    "error": _safe_failure(exc),
                })
    else:
        availability_status = str(
            previous.get("tmdb_watch_providers_status") or "fresh"
        )

    record = {
        "ids": ids,
        "tmdb_full": details if isinstance(details, dict) else {},
        "watch_providers": providers if isinstance(providers, dict) else {},
        # Keep prior timestamps on stale/expired content; unavailable content
        # has no successful timestamp and is therefore retried next run.
        "tmdb_details_fetched_at": details_at,
        "tmdb_details_status": detail_status,
        "tmdb_watch_providers_fetched_at": providers_at,
        "tmdb_watch_providers_status": availability_status,
    }
    return record, errors


def enrich_tmdb_snapshots(
    snapshots: list[Any],
    additional_items: dict[tuple[str, str], dict[str, Any]] | None = None,
    previous_detail_index: dict[tuple[str, str], str] | None = None,
    now: datetime | None = None,
    public_base_url: str = PUBLIC_CATALOGUE_BASE,
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    """Attach full details and independently refreshed availability to each unique item."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    previous_detail_index = previous_detail_index or {}
    additional_items = additional_items or {}

    items_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for snapshot in snapshots:
        if snapshot.provider_id != "tmdb" or snapshot.media_type not in {"movie", "series"}:
            continue
        for item in snapshot.items:
            if isinstance(item, dict) and item.get("id") is not None:
                key = (snapshot.media_type, str(item["id"]))
                items_by_key.setdefault(key, []).append(item)

    for key, item in additional_items.items():
        items_by_key.setdefault(key, []).append(item)

    refreshed: dict[tuple[str, str], dict[str, Any]] = {}
    all_errors: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []

    def work(key: tuple[str, str]):
        old = _load_previous_item(key, previous_detail_index, public_base_url)
        return key, _refresh_record(key, old, now)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(work, key) for key in items_by_key]
        for future in as_completed(futures):
            try:
                key, (record, errors) = future.result()
                refreshed[key] = record
                all_errors.extend(errors)
            except Exception as exc:
                failures.append({"error": str(exc)[:300]})

    if failures:
        # Do not publish a partially enriched catalogue. The workflow skips
        # Pages deployment on failure, retaining the last complete release.
        raise RuntimeError(
            f"TMDB enrichment incomplete for {len(failures)} item(s); "
            f"last complete catalogue will remain published. Sample: {failures[:3]}"
        )

    for key, refs in items_by_key.items():
        record = refreshed.get(key)
        if record is not None:
            for item in refs:
                item["tmdb_enrichment"] = record
                item["id"] = int(key[1]) if key[1].isdigit() else item.get("id")

    report = {
        "unique_tmdb_titles": len(items_by_key),
        "detail_titles_refreshed": sum(
            1 for r in refreshed.values() if r.get("tmdb_details_status") == "fresh"
        ),
        "availability_records_refreshed": sum(
            1 for r in refreshed.values() if r.get("tmdb_watch_providers_status") == "fresh"
        ),
        "detail_refresh_days": int(DETAIL_REFRESH_AGE.total_seconds() // 86400),
        "availability_refresh_hours": int(AVAILABILITY_REFRESH_AGE.total_seconds() // 3600),
        "hard_cache_limit_days": int(DETAIL_HARD_MAX_AGE.total_seconds() // 86400),
        "stale_refresh_errors": all_errors,
        "unavailable_detail_items": sum(
            1 for r in refreshed.values()
            if r.get("tmdb_details_status") == "unavailable"
        ),
        "unavailable_availability_items": sum(
            1 for r in refreshed.values()
            if r.get("tmdb_watch_providers_status") == "unavailable"
        ),
        "failed_items": 0,
    }
    return refreshed, report
