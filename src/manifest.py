"""Build a versioned catalogue release from provider snapshots."""

from __future__ import annotations

from datetime import datetime
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


def _images(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "poster": item.get("poster") or item.get("poster_path") or None,
        "backdrop": item.get("background") or item.get("backdrop_path") or None,
        "logo": item.get("logo") or None,
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
        "rating": item.get("rating"),
        "rating_source": item.get("rating_source"),
        "ratings": item.get("ratings") if isinstance(item.get("ratings"), dict) else {},
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

        media_type = media_kind
        merged: Dict[str, Dict[str, Any]] = {}
        identities: Dict[str, Dict[str, Any]] = {}
        attributions: Dict[str, List[Dict[str, Any]]] = {}

        for snapshot in row_snapshots:
            freshness = snapshot_status(snapshot, retention_policy, now)
            weight = float(provider_weights.get(snapshot.provider_id, 1.0))

            for position, raw_item in enumerate(snapshot.items, start=1):
                media_id = resolve_identity(media_type, raw_item, identities)
                existing = merged.get(media_id)
                item = merge_item(media_type, existing, raw_item, snapshot.provider_id)
                item["_viewsync_id"] = media_id
                item["source_rank"] = position
                merged[media_id] = item

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

        rankings = build_ranking(
            row_snapshots,
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

        providers = {snapshot.provider_id for snapshot in row_snapshots}
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
