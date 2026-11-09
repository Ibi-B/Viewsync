"""Build a versioned catalogue release from provider snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from .fetch import SourceSnapshot
from .identity import media_identity
from .merge_metadata import merge_item
from .rank import build_ranking, order_items


def _row_snapshots(
    row: Dict[str, Any],
    snapshots: List[SourceSnapshot],
) -> List[SourceSnapshot]:
    source_lists = set(row.get("source_lists", []))
    return [snapshot for snapshot in snapshots if snapshot.request_id in source_lists]


def build_release(
    rows: List[Dict[str, Any]],
    snapshots: List[SourceSnapshot],
    now: datetime,
) -> Dict[str, Any]:
    """Merge, rank, and structure snapshots into a versioned release."""

    release_rows: List[Dict[str, Any]] = []

    for row in rows:
        row_snapshots = _row_snapshots(row, snapshots)
        if not row_snapshots:
            continue

        media_type = str(row.get("type") or "")
        merged: Dict[str, Dict[str, Any]] = {}

        for snapshot in row_snapshots:
            for position, raw_item in enumerate(snapshot.items, start=1):
                identity = media_identity(media_type, raw_item)
                media_id = identity["id"]
                existing = merged.get(media_id)
                item = merge_item(media_type, existing, raw_item, snapshot.provider_id)
                item["_viewsync_id"] = media_id
                item["source_rank"] = position
                merged[media_id] = item

        rankings = build_ranking(row_snapshots)
        ordered_items = order_items(list(merged.values()), rankings)

        release_items: List[Dict[str, Any]] = []
        for item in ordered_items:
            ranking = rankings.get(item["_viewsync_id"], {})
            item["ranking"] = {
                "consensus_score": ranking.get("consensus_score", 0.0),
                "provider_count": ranking.get("source_count", 0),
                "best_rank": ranking.get("best_rank"),
                "average_rank": ranking.get("average_rank"),
            }
            release_items.append(item)

        providers = {snapshot.provider_id for snapshot in row_snapshots}
        release_rows.append(
            {
                "id": str(row["id"]),
                "title": str(row.get("name") or row["id"]),
                "media_type": media_type,
                "data_updated_at": now.isoformat(),
                "status": "active",
                "configured_provider_count": len(providers),
                "contributing_provider_count": len(providers),
                "source_lists": list(row.get("source_lists", [])),
                "items": release_items,
            }
        )

    return {
        "schema_version": 1,
        "release_id": now.strftime("%Y%m%dT%H%M%SZ"),
        "generated_at": now.isoformat(),
        "ranking_version": "rrf-v1",
        "rows": release_rows,
    }
