"""Build a versioned catalogue release from provider snapshots."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from .fetch import SourceSnapshot
from .identity import media_identity, resolve_identity
from .merge_metadata import merge_item
from .rank import build_ranking, order_items
from .state import snapshot_age_hours, snapshot_status

SUPPORTED_MEDIA_KINDS = {"movie", "series"}


def _row_snapshots(
    row: Dict[str, Any],
    snapshots: List[SourceSnapshot],
) -> List[SourceSnapshot]:
    source_lists = set(row.get("source_lists", []))
    return [snapshot for snapshot in snapshots if snapshot.request_id in source_lists]


def _media_kind(row: Dict[str, Any]) -> str | None:
    media_kind = str(row.get("media_kind") or row.get("type") or "")
    return media_kind if media_kind in SUPPORTED_MEDIA_KINDS else None

def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _matches_row_date(row: Dict[str, Any], item: Dict[str, Any], today: date) -> bool:
    """Enforce New/Upcoming membership again at publication time."""
    mode = str(row.get("date_mode") or "none")
    if mode == "none":
        return True
    field = str(row.get("date_field") or (
        "release_date" if _media_kind(row) == "movie" else "first_air_date"
    ))
    release = _parse_date(item.get(field))
    if release is None:
        return False
    if mode == "recent":
        return today - timedelta(days=30) <= release <= today
    if mode == "future":
        return today + timedelta(days=1) <= release <= today + timedelta(days=180)
    raise ValueError(f"Unsupported date mode for row {row.get('id')!r}: {mode}")


def _catalog_freshness(
    snapshots: List[SourceSnapshot],
    policy: Dict[str, Any],
    now: datetime,
) -> Dict[str, Any]:
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
    """Return an absolute TMDB image URL, preserving existing absolute URLs."""
    if not isinstance(value, str) or not value.strip():
        return None

    value = value.strip()
    if value.startswith(("https://", "http://")):
        return value
    if value.startswith("/") and not value.startswith("//"):
        return f"https://image.tmdb.org/t/p/{size}{value}"
    return None


def _images(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "poster": _tmdb_image_url(item.get("poster") or item.get("poster_path"), "w500"),
        "backdrop": _tmdb_image_url(
            item.get("backdrop") or item.get("background") or item.get("backdrop_path"),
            "w1280",
        ),
        "logo": _tmdb_image_url(item.get("logo"), "w500"),
    }


def _metadata(item: Dict[str, Any]) -> Dict[str, Any]:
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
        "release_date": item.get("release_date"),
        "rating": item.get("rating"),
        "rating_source": item.get("rating_source"),
        "ratings": item.get("ratings", {}),
        "field_sources": item.get("field_sources", {}),
        "original_title": item.get("original_title"),
        "original_language": item.get("original_language"),
        "popularity": item.get("popularity"),
        "vote_count": item.get("vote_count"),
        "quality": item.get("quality", {}),
    }


def build_release(
    rows: List[Dict[str, Any]],
    snapshots: List[SourceSnapshot],
    now: datetime,
    retention_policy: Dict[str, Any] | None = None,
    provider_weights: Dict[str, float] | None = None,
) -> Dict[str, Any]:
    """Merge, rank, and structure snapshots into a BeastED-facing v2 release."""

    retention_policy = retention_policy or {}
    provider_weights = provider_weights or {}
    release_rows: List[Dict[str, Any]] = []

    for row in rows:
        media_kind = _media_kind(row)
        if media_kind is None:
            continue

        row_snapshots = _row_snapshots(row, snapshots)
        if not row_snapshots:
            continue

        # Retained snapshots can outlive the request that produced them.
        # Re-apply the row date contract so a stale snapshot cannot publish
        # the same title into both New and Upcoming.
        today = now.date()
        row_snapshots = [
            SourceSnapshot(
                request_id=snapshot.request_id,
                provider_id=snapshot.provider_id,
                list_id=snapshot.list_id,
                media_type=snapshot.media_type,
                fetched_at=snapshot.fetched_at,
                items=[item for item in snapshot.items if _matches_row_date(row, item, today)],
                raw_payloads=snapshot.raw_payloads,
            )
            for snapshot in row_snapshots
        ]

        media_type = media_kind
        merged: Dict[str, Dict[str, Any]] = {}
        identities: Dict[str, Dict[str, Any]] = {}
        attributions: Dict[str, List[Dict[str, Any]]] = {}
        ranking_snapshots: List[SourceSnapshot] = []

        for snapshot in row_snapshots:
            freshness = snapshot_status(snapshot, retention_policy, now)
            weight = float(provider_weights.get(snapshot.provider_id, 1.0))

            ranked_items: List[Dict[str, Any]] = []
            for position, raw_item in enumerate(snapshot.items, start=1):
                media_id = resolve_identity(media_type, raw_item, identities, snapshot.provider_id)
                existing = merged.get(media_id)
                item = merge_item(media_type, existing, raw_item, snapshot.provider_id)
                item["_viewsync_id"] = media_id
                item["source_rank"] = position
                merged[media_id] = item
                ranked_item = dict(raw_item)
                ranked_item["_viewsync_id"] = media_id
                ranked_item["source_rank"] = position
                ranked_items.append(ranked_item)

                attributions.setdefault(media_id, []).append(
                    {
                        "provider_id": snapshot.provider_id,
                        "list_id": snapshot.list_id,
                        "rank": position,
                        "weight": weight,
                        "fetched_at": snapshot.fetched_at,
                        "freshness": freshness,
                    }
                )

            ranking_snapshots.append(
                SourceSnapshot(
                    request_id=snapshot.request_id,
                    provider_id=snapshot.provider_id,
                    list_id=snapshot.list_id,
                    media_type=snapshot.media_type,
                    fetched_at=snapshot.fetched_at,
                    items=ranked_items,
                    raw_payloads=snapshot.raw_payloads,
                )
            )

        rankings = build_ranking(
            ranking_snapshots,
            provider_weights=provider_weights,
        )
        ordered_items = order_items(list(merged.values()), rankings)

        release_items: List[Dict[str, Any]] = []
        for item in ordered_items:
            media_id = item["_viewsync_id"]
            ranking = rankings.get(media_id, {})

            release_items.append(
                {
                    "id": media_id,
                    "media_kind": media_kind,
                    "title": item.get("title") or item.get("name") or "",
                    "year": item.get("year"),
                    "ids": item.get("ids", {}),
                    "release_date": item.get("release_date"),
                    "images": _images(item),
                    "metadata": _metadata(item),
                    "source_attribution": attributions.get(media_id, []),
                    "ranking": {
                        "consensus_score": ranking.get("consensus_score", 0.0),
                        "provider_count": ranking.get("source_count", 0),
                        "best_rank": ranking.get("best_rank"),
                        "average_rank": ranking.get("average_rank"),
                    },
                }
            )

        providers = {snapshot.provider_id for snapshot in row_snapshots if snapshot.items}
        release_rows.append(
            {
                "id": str(row["id"]),
                "title": str(row.get("name") or row["id"]),
                "media_type": media_type,
                "media_kind": media_kind,
                "data_updated_at": now.isoformat(),
                "status": "active",
                "configured_provider_count": len(providers),
                "contributing_provider_count": len(providers),
                "source_lists": list(row.get("source_lists", [])),
                "items": release_items,
            }
        )

    return {
        "schema_version": 2,
        "release_id": now.strftime("%Y%m%dT%H%M%SZ"),
        "generated_at": now.isoformat(),
        "ranking_version": "rrf-v1",
        "catalog_freshness": _catalog_freshness(snapshots, retention_policy, now),
        "rows": release_rows,
    }
