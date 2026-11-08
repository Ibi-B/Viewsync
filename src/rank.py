"""Reciprocal Rank Fusion and consensus ranking."""

from __future__ import annotations

from typing import Any

from .identity import same_media


def rrf_score(
    ranks: list[int],
    *,
    k: int = 60,
    provider_weight: float = 1.0,
    list_count: int = 1,
) -> float:
    """Calculate an RRF score for one item.

    A provider's weight is divided across all of its contributing lists so that
    additional lists from the same provider do not multiply its influence.
    """

    if not ranks or list_count <= 0:
        return 0.0
    per_list_weight = provider_weight / list_count
    return sum(per_list_weight / (k + rank) for rank in ranks)


def build_ranking(
    snapshots: list[Any],
    *,
    k: int = 60,
    provider_weights: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    provider_weights = provider_weights or {}
    provider_lists: dict[str, list[Any]] = {}

    for snapshot in snapshots:
        provider_lists.setdefault(snapshot.provider_id, []).append(snapshot)

    entries: dict[str, dict[str, Any]] = {}

    for provider_id, provider_snapshots in provider_lists.items():
        list_count = len(provider_snapshots)
        weight = float(provider_weights.get(provider_id, 1.0))

        for snapshot in provider_snapshots:
            seen_in_list: set[str] = set()
            for item in snapshot.items:
                media_id = item.get("_viewsync_id")
                if not media_id or media_id in seen_in_list:
                    continue
                seen_in_list.add(media_id)

                entry = entries.setdefault(
                    media_id,
                    {
                        "consensus_score": 0.0,
                        "source_count": 0,
                        "source_ranks": {},
                        "best_rank": None,
                        "rank_sum": 0,
                        "rank_count": 0,
                    },
                )

                rank = int(item["source_rank"])
                provider_ranks = entry["source_ranks"].setdefault(provider_id, [])
                provider_ranks.append(rank)
                entry["consensus_score"] += weight / (list_count * (k + rank))
                entry["rank_sum"] += rank
                entry["rank_count"] += 1

                if entry["best_rank"] is None or rank < entry["best_rank"]:
                    entry["best_rank"] = rank

    for media_id, entry in entries.items():
        entry["source_count"] = len(entry["source_ranks"])
        entry["average_rank"] = (
            entry["rank_sum"] / entry["rank_count"] if entry["rank_count"] else None
        )

    return entries


def order_items(
    items: list[dict[str, Any]],
    rankings: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    def sort_key(item: dict[str, Any]) -> tuple:
        media_id = item["_viewsync_id"]
        entry = rankings.get(media_id, {})
        return (
            -entry.get("consensus_score", 0.0),
            -entry.get("source_count", 0),
            entry.get("best_rank") if entry.get("best_rank") is not None else 10**9,
            media_id,
        )

    return sorted(items, key=sort_key)
