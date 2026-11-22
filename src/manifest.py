"""Build a slim versioned catalogue release from provider snapshots.

Full TMDB payloads live once in per-item detail documents. Row JSON and
provider-shelf JSON contain only display metadata plus details_path references.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any

from .fetch import SourceSnapshot
from .identity import resolve_identity
from .merge_metadata import merge_item
from .rank import build_ranking, order_items
from .state import snapshot_age_hours, snapshot_status

SUPPORTED_MEDIA_KINDS = {"movie", "series"}


def _row_snapshots(row: dict[str, Any], snapshots: list[SourceSnapshot]) -> list[SourceSnapshot]:
    source_lists = set(row.get("source_lists", []))
    return [snapshot for snapshot in snapshots if snapshot.request_id in source_lists]


def _media_kind(row: dict[str, Any]) -> str | None:
    media_kind = str(row.get("media_kind") or row.get("type") or "")
    return media_kind if media_kind in SUPPORTED_MEDIA_KINDS else None


def _catalog_freshness(
    snapshots: list[SourceSnapshot],
    policy: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    ages = [snapshot_age_hours(snapshot, now) for snapshot in snapshots]
    statuses = [snapshot_status(snapshot, policy, now) for snapshot in snapshots]
    if not statuses:
        overall = "expired"
    elif all(status == "fresh" for status in statuses):
        overall = "fresh"
    elif any(status == "fresh" for status in statuses):
        overall = "mixed"
    elif all(status in {"retained_full", "retained_declining"} for status in statuses):
        overall = "retained"
    else:
        overall = "expired"
    return {
        "status": overall,
        "oldest_source_age_hours": max(ages) if ages else None,
        "newest_source_age_hours": min(ages) if ages else None,
        "snapshot_statuses": statuses,
        "age_basis": "provider snapshot fetched_at",
    }


def _tmdb_image_url(value: Any, size: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value.startswith(("https://", "http://")):
        return value
    if value.startswith("/") and not value.startswith("//"):
        return f"https://image.tmdb.org/t/p/{size}{value}"
    return None


def _images(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "poster": _tmdb_image_url(item.get("poster") or item.get("poster_path"), "w500"),
        "backdrop": _tmdb_image_url(
            item.get("background") or item.get("backdrop") or item.get("backdrop_path"),
            "w1280",
        ),
        "logo": _tmdb_image_url(item.get("logo") or item.get("logo_path"), "w500"),
    }


def _metadata(item: dict[str, Any]) -> dict[str, Any]:
    genres = item.get("genres") or []
    if isinstance(genres, str):
        genres = [genres]
    runtime = item.get("runtime") or item.get("runtime_minutes")
    if isinstance(runtime, str) and runtime.isdigit():
        runtime = int(runtime)
    if not isinstance(runtime, (int, float)):
        runtime = None
    return {
        "overview": item.get("description") or item.get("overview") or None,
        "genres": genres,
        "runtime_minutes": runtime,
        "release_date": item.get("release_date") or item.get("first_air_date"),
        "rating": item.get("rating"),
        "rating_source": item.get("rating_source"),
        "ratings": item.get("ratings", {}),
        "field_sources": item.get("field_sources", {}),
        "original_title": item.get("original_title") or item.get("original_name"),
        "original_language": item.get("original_language"),
        "popularity": item.get("popularity"),
        "vote_count": item.get("vote_count"),
    }


def _detail_path(detail_document: dict[str, Any]) -> str:
    """Return a stable content-addressed path shared across release generations."""
    encoded = json.dumps(
        detail_document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"details/{digest}.json"


def _discovery_quality(
    item: dict[str, Any],
    media_type: str,
    now: datetime,
) -> dict[str, Any]:
    """Classify promotional eligibility without removing items from full rows."""
    images = _images(item)
    has_artwork = bool(images.get("poster") or images.get("backdrop"))
    ids = item.get("ids") if isinstance(item.get("ids"), dict) else {}
    has_tmdb_id = bool(ids.get("tmdb") or item.get("tmdb_id"))
    title = str(item.get("title") or item.get("name") or "").strip()
    overview = str(item.get("description") or item.get("overview") or "").strip()
    genres = item.get("genres") or []
    if isinstance(genres, str):
        genres = [genres]
    has_genres = any(
        (isinstance(genre, str) and genre.strip())
        or (isinstance(genre, dict) and str(genre.get("name") or "").strip())
        for genre in genres
    )
    has_description = bool(overview) or has_genres

    raw_date = (
        item.get("release_date")
        or item.get("first_air_date")
        or item.get("date")
    )
    parsed_date = None
    if isinstance(raw_date, str):
        candidate = raw_date.strip()
        try:
            parsed_date = date.fromisoformat(candidate[:10])
        except ValueError:
            parsed_date = None

    today = now.date()
    base_reasons: list[str] = []
    if parsed_date is None:
        base_reasons.append("invalid_release_date")
    if not has_artwork:
        base_reasons.append("missing_tmdb_artwork")
    if not has_tmdb_id:
        base_reasons.append("missing_tmdb_id")
    if not title:
        base_reasons.append("missing_title")
    if not has_description:
        base_reasons.append("missing_overview_or_genre")

    new_reasons = list(base_reasons)
    if parsed_date is not None and not (today - timedelta(days=7) <= parsed_date <= today):
        new_reasons.append("release_date_outside_past_7_days")
    coming_reasons = list(base_reasons)
    if parsed_date is not None and not (today < parsed_date <= today + timedelta(days=180)):
        coming_reasons.append("release_date_outside_next_180_days")

    return {
        "new_this_week_eligible": not new_reasons,
        "coming_soon_eligible": not coming_reasons,
        "reasons": {
            "new_this_week": new_reasons,
            "coming_soon": coming_reasons,
        },
    }


def _enriched_identity(media_type: str, raw_item: dict[str, Any], provider_id: str) -> dict[str, Any]:
    identity_item = dict(raw_item)
    enrichment = raw_item.get("tmdb_enrichment")
    details = enrichment.get("tmdb_full") if isinstance(enrichment, dict) else None
    if isinstance(details, dict):
        enriched = dict(details)
        enriched.update(identity_item)
        external_ids = details.get("external_ids")
        if isinstance(external_ids, dict) and external_ids.get("imdb_id"):
            enriched["imdb_id"] = external_ids["imdb_id"]
        if enriched.get("tmdb_id") is None and details.get("id") is not None:
            enriched["tmdb_id"] = details["id"]
        identity_item = enriched
    retained_ids = enrichment.get("ids") if isinstance(enrichment, dict) else None
    if isinstance(retained_ids, dict):
        if retained_ids.get("tmdb"):
            identity_item["tmdb_id"] = retained_ids["tmdb"]
        if retained_ids.get("imdb"):
            identity_item["imdb_id"] = retained_ids["imdb"]
    if identity_item.get("tmdb_id") is None and provider_id == "tmdb" and identity_item.get("id") is not None:
        identity_item["tmdb_id"] = identity_item["id"]
    return identity_item


def _make_detail_document(
    media_id: str,
    media_type: str,
    item: dict[str, Any],
    source_item: dict[str, Any],
) -> dict[str, Any]:
    enrichment = item.get("tmdb_enrichment")
    if not isinstance(enrichment, dict):
        enrichment = source_item.get("tmdb_enrichment")
    enrichment = enrichment if isinstance(enrichment, dict) else {}
    details = enrichment.get("tmdb_full")
    watch_providers = enrichment.get("watch_providers")
    retained_ids = item.get("ids")
    if not isinstance(retained_ids, dict) or not retained_ids:
        retained_ids = enrichment.get("ids", {})
    return {
        "schema_version": 1,
        "id": media_id,
        "media_kind": media_type,
        "title": item.get("title") or item.get("name") or source_item.get("title") or source_item.get("name") or "",
        "year": item.get("year") or source_item.get("year"),
        "release_date": item.get("release_date") or source_item.get("release_date"),
        "images": item.get("images") or _images(item),
        "metadata": _metadata(item),
        "ids": retained_ids,
        "tmdb_full": details if isinstance(details, dict) else {},
        "watch_providers": watch_providers if isinstance(watch_providers, dict) else {},
        "tmdb_details_fetched_at": enrichment.get("tmdb_details_fetched_at"),
        "tmdb_details_status": enrichment.get("tmdb_details_status"),
        "tmdb_watch_providers_fetched_at": enrichment.get("tmdb_watch_providers_fetched_at"),
        "tmdb_watch_providers_status": enrichment.get("tmdb_watch_providers_status"),
        # Keep the source-list record too, but only once in this detail file.
        # It preserves TMDB discovery fields not yet mapped to the slim row.
        "source_item": {
            key: value for key, value in source_item.items()
            if key != "tmdb_enrichment"
        },
    }


def build_release(
    rows: list[dict[str, Any]],
    snapshots: list[SourceSnapshot],
    now: datetime,
    retention_policy: dict[str, Any] | None = None,
    provider_weights: dict[str, float] | None = None,
    watch_regions: list[dict[str, Any]] | None = None,
    provider_shelves: dict[str, list[dict[str, Any]]] | None = None,
    item_enrichments: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge and rank global lists while publishing heavy per-item data once."""
    retention_policy = retention_policy or {}
    provider_weights = provider_weights or {}
    provider_shelves = provider_shelves or {}
    item_enrichments = item_enrichments or {}
    release_id = now.strftime("%Y%m%dT%H%M%SZ")
    release_rows: list[dict[str, Any]] = []
    item_details: dict[str, dict[str, Any]] = {}
    detail_paths_by_media_id: dict[tuple[str, str], str] = {}
    details_by_tmdb: dict[tuple[str, str], tuple[str, dict[str, Any], dict[str, Any]]] = {}

    for row in rows:
        media_type = _media_kind(row)
        if media_type is None:
            continue
        row_snapshots = _row_snapshots(row, snapshots)
        if not row_snapshots:
            continue

        merged: dict[str, dict[str, Any]] = {}
        identities: dict[str, dict[str, Any]] = {}
        attributions: dict[str, list[dict[str, Any]]] = {}
        source_records: dict[str, dict[str, Any]] = {}
        ranking_snapshots: list[SourceSnapshot] = []

        for snapshot in row_snapshots:
            freshness = snapshot_status(snapshot, retention_policy, now)
            weight = float(provider_weights.get(snapshot.provider_id, 1.0))
            ranked_items: list[dict[str, Any]] = []

            for position, raw_item in enumerate(snapshot.items, start=1):
                identity_item = _enriched_identity(media_type, raw_item, snapshot.provider_id)
                media_id = resolve_identity(media_type, identity_item, identities, snapshot.provider_id)
                existing = merged.get(media_id)
                item = merge_item(media_type, existing, raw_item, snapshot.provider_id)
                item["_viewsync_id"] = media_id
                item["source_rank"] = position
                merged[media_id] = item
                source_records.setdefault(media_id, raw_item)

                ranked = dict(raw_item)
                ranked["_viewsync_id"] = media_id
                ranked["source_rank"] = position
                ranked_items.append(ranked)

                attributions.setdefault(media_id, []).append({
                    "provider_id": snapshot.provider_id,
                    "list_id": snapshot.list_id,
                    "rank": position,
                    "weight": weight,
                    "fetched_at": snapshot.fetched_at,
                    "freshness": freshness,
                })

                tmdb_id = item.get("ids", {}).get("tmdb")
                enrichment = raw_item.get("tmdb_enrichment")
                if tmdb_id is not None and isinstance(enrichment, dict):
                    details_by_tmdb[(media_type, str(tmdb_id))] = (
                        media_id, item, raw_item
                    )

            ranking_snapshots.append(SourceSnapshot(
                request_id=snapshot.request_id,
                provider_id=snapshot.provider_id,
                list_id=snapshot.list_id,
                media_type=snapshot.media_type,
                fetched_at=snapshot.fetched_at,
                items=ranked_items,
                raw_payloads=snapshot.raw_payloads,
            ))

        rankings = build_ranking(ranking_snapshots, provider_weights=provider_weights)
        ordered_items = order_items(list(merged.values()), rankings)
        release_items: list[dict[str, Any]] = []

        for item in ordered_items:
            media_id = item["_viewsync_id"]
            source_item = source_records.get(media_id, {})
            tmdb_id = item.get("ids", {}).get("tmdb")
            enrichment = item.get("tmdb_enrichment") or source_item.get("tmdb_enrichment") or {}
            if tmdb_id is not None and isinstance(enrichment, dict):
                key = (media_type, str(tmdb_id))
                details_by_tmdb[key] = (media_id, item, source_item)
            detail_doc = _make_detail_document(media_id, media_type, item, source_item)
            detail_path = _detail_path(detail_doc)
            detail_paths_by_media_id[(media_type, media_id)] = detail_path
            item_details.setdefault(detail_path, detail_doc)

            ranking = rankings.get(media_id, {})
            release_items.append({
                "id": media_id,
                "media_kind": media_type,
                "title": item.get("title") or item.get("name") or "",
                "year": item.get("year"),
                "ids": item.get("ids", {}),
                "release_date": item.get("release_date"),
                "images": _images(item),
                "metadata": _metadata(item),
                "discovery_quality": _discovery_quality(item, media_type, now),
                "details_path": detail_path,
                "popularity": item.get("popularity"),
                "vote_count": item.get("vote_count"),
                "source_attribution": attributions.get(media_id, []),
                "ranking": {
                    "consensus_score": ranking.get("consensus_score", 0.0),
                    "provider_count": ranking.get("source_count", 0),
                    "best_rank": ranking.get("best_rank"),
                    "average_rank": ranking.get("average_rank"),
                },
            })

        providers = {snapshot.provider_id for snapshot in row_snapshots}
        release_rows.append({
            "id": str(row["id"]),
            "title": str(row.get("name") or row["id"]),
            "media_type": media_type,
            "media_kind": media_type,
            "data_updated_at": now.isoformat(),
            "status": "active",
            "configured_provider_count": len(providers),
            "contributing_provider_count": len(providers),
            "source_lists": list(row.get("source_lists", [])),
            "items": release_items,
        })

    # Detail documents for provider-discover titles that are not in the six
    # global lists. Their canonical identity is still the TMDB ID.
    for (media_type, tmdb_id), enrichment in item_enrichments.items():
        if (media_type, str(tmdb_id)) in details_by_tmdb:
            continue
        media_id = f"{media_type}:tmdb:{tmdb_id}"
        discovered = next(
            (
                item
                for shelves in provider_shelves.values()
                for shelf in shelves
                if shelf.get("media_kind") == media_type
                for item in shelf.get("items", [])
                if str(item.get("tmdb_id")) == str(tmdb_id)
            ),
            {},
        )
        source_item = dict(discovered)
        source_item["id"] = int(tmdb_id) if str(tmdb_id).isdigit() else tmdb_id
        source_item["tmdb_enrichment"] = enrichment
        tmdb_full = enrichment.get("tmdb_full")
        external_ids = (
            tmdb_full.get("external_ids")
            if isinstance(tmdb_full, dict) else None
        )
        retained_ids = enrichment.get("ids")
        canonical_ids = (
            {str(key): str(value) for key, value in retained_ids.items()
             if value not in (None, "")}
            if isinstance(retained_ids, dict) else {}
        )
        canonical_ids.setdefault("tmdb", str(tmdb_id))
        if isinstance(external_ids, dict) and external_ids.get("imdb_id"):
            canonical_ids.setdefault("imdb", str(external_ids["imdb_id"]))
        item = {
            "ids": canonical_ids,
            "tmdb_enrichment": enrichment,
            "title": discovered.get("title") or "",
            "year": discovered.get("year"),
            "release_date": discovered.get("release_date"),
            "popularity": discovered.get("popularity"),
            "vote_count": discovered.get("vote_count"),
        }
        detail_doc = _make_detail_document(media_id, media_type, item, source_item)
        detail_path = _detail_path(detail_doc)
        item_details.setdefault(detail_path, detail_doc)
        detail_paths_by_media_id[(media_type, media_id)] = detail_path
        details_by_tmdb[(media_type, str(tmdb_id))] = (
            media_id, item, source_item
        )

    # Publish mixed-media promotional rows with strict discovery-quality
    # eligibility. The six complete source rows remain unchanged and retain
    # every item, regardless of artwork, votes, overview or date.
    for row_id, title, quality_key in (
        ("new-this-week", "New this week", "new_this_week_eligible"),
        ("coming-soon", "Coming soon", "coming_soon_eligible"),
    ):
        selected: dict[str, dict[str, Any]] = {}
        for source_row in release_rows:
            for item in source_row["items"]:
                quality = item.get("discovery_quality") or {}
                if quality.get(quality_key) is True:
                    selected.setdefault(item["id"], item)
        release_rows.append({
            "id": row_id,
            "title": title,
            "media_type": "mixed",
            "media_kind": "mixed",
            "data_updated_at": now.isoformat(),
            "status": "active",
            "configured_provider_count": 1,
            "contributing_provider_count": 1,
            "source_lists": [
                "new_movies", "new_series", "upcoming_movies", "upcoming_series"
            ],
            "quality_filter": quality_key,
            "items": list(selected.values()),
        })

    published_regions: list[dict[str, Any]] = []
    published_provider_shelves: list[dict[str, Any]] = []
    for region in watch_regions or []:
        region_code = str(region.get("iso_code") or "").upper()
        shelves = provider_shelves.get(region_code, [])
        if not region_code or not shelves:
            continue
        shelf_path = f"releases/{release_id}/provider-shelves/{region_code}.json"
        published_regions.append({
            **region,
            "provider_shelves_path": shelf_path,
        })
        output_shelves: list[dict[str, Any]] = []
        for shelf in shelves:
            shelf_items: list[dict[str, Any]] = []
            for raw in shelf.get("items", []):
                tmdb_id = str(raw.get("tmdb_id") or "")
                media_kind = str(raw.get("media_kind") or shelf.get("media_kind") or "")
                details_entry = details_by_tmdb.get((media_kind, tmdb_id))
                if details_entry is None:
                    raise ValueError(
                        f"Missing TMDB enrichment for provider shelf item {media_kind}:{tmdb_id}"
                    )
                media_id, item, _ = details_entry
                detail_path = detail_paths_by_media_id.get((media_kind, media_id))
                if detail_path is None:
                    raise ValueError(
                        f"Missing published detail path for {media_kind}:{media_id}"
                    )
                shelf_items.append({
                    "id": media_id,
                    "tmdb_id": tmdb_id,
                    "media_kind": media_kind,
                    "title": raw.get("title") or item.get("title") or "",
                    "year": raw.get("year") or item.get("year"),
                    "release_date": raw.get("release_date") or item.get("release_date"),
                    "images": raw.get("images") or _images(item),
                    "popularity": raw.get("popularity", item.get("popularity")),
                    "rating": raw.get("rating", item.get("rating")),
                    "vote_count": raw.get("vote_count", item.get("vote_count")),
                    "rank": raw.get("rank"),
                    "details_path": detail_path,
                    "ids": item.get("ids", {"tmdb": tmdb_id}),
                })
            if not shelf_items:
                continue
            output_shelves.append({
                key: value for key, value in shelf.items() if key != "items"
            } | {"items": shelf_items})
        if output_shelves:
            published_provider_shelves.append({
                "region": region_code,
                "shelves": output_shelves,
            })

    return {
        "schema_version": 2,
        "release_id": release_id,
        "generated_at": now.isoformat(),
        "ranking_version": "rrf-v1",
        "catalog_freshness": _catalog_freshness(snapshots, retention_policy, now),
        "watch_regions": published_regions,
        "provider_shelves": published_provider_shelves,
        "item_details": item_details,
        "rows": release_rows,
    }
