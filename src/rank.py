"""Reciprocal Rank Fusion and consensus ranking."""

from __future__ import annotations

import math
from typing import Any

from .identity import same_media


class RankingError(ValueError):
    """Raised when ranking inputs or configuration are invalid."""


def _validate_k(k: int) -> int:
    if not isinstance(k, int) or isinstance(k, bool) or k <= 0:
        raise RankingError(f"RRF damping constant k must be a positive integer, got {k!r}")
    return k


def _validate_weight(provider_id: str, weight: Any) -> float:
    if isinstance(weight, bool) or not isinstance(weight, (int, float)):
        raise RankingError(f"Provider weight for {provider_id!r} must be numeric, got {weight!r}")

    value = float(weight)
    if not math.isfinite(value) or value <= 0:
        raise RankingError(
            f"Provider weight for {provider_id!r} must be finite and positive, got {value!r}"
        )
    return value


def _validate_rank(provider_id: str, rank: Any) -> int:
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
        raise RankingError(
            f"Source rank for provider {provider_id!r} must be a positive integer, got {rank!r}"
        )
    return rank


def _snapshot_key(snapshot: Any) -> tuple[str, str, str]:
    return (
        str(snapshot.provider_id),
        str(snapshot.request_id),
        str(snapshot.list_id),
    )


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

    k = _validate_k(k)
    provider_weight = _validate_weight("rrf_score", provider_weight)

    if not ranks or list_count <= 0:
        return 0.0

    if not isinstance(list_count, int) or isinstance(list_count, bool) or list_count <= 0:
        raise RankingError(f"List count must be a positive integer, got {list_count!r}")

    validated_ranks = [_validate_rank("rrf_score", rank) for rank in ranks]
    per_list_weight = provider_weight / list_count
    return sum(per_list_weight / (k + rank) for rank in validated_ranks)


def build_ranking(
    snapshots: list[Any],
    *,
    k: int = 60,
    provider_weights: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build consensus rankings while preventing duplicate snapshot weighting."""

    k = _validate_k(k)
    provider_weights = provider_weights or {}

    provider_lists: dict[str, list[Any]] = {}
    seen_snapshots: set[tuple[str, str, str]] = set()

    for snapshot in snapshots:
        key = _snapshot_key(snapshot)
        if key in seen_snapshots:
            continue

        seen_snapshots.add(key)
        provider_lists.setdefault(snapshot.provider_id, []).append(snapshot)

    entries: dict[str, dict[str, Any]] = {}

    for provider_id, provider_snapshots in provider_lists.items():
        list_count = len(provider_snapshots)
        weight = _validate_weight(provider_id, provider_weights.get(provider_id, 1.0))

        for snapshot in provider_snapshots:
            seen_in_list: set[str] = set()

            for item in snapshot.items:
                media_id = item.get("_viewsync_id")
                if not media_id or media_id in seen_in_list:
                    continue

                try:
                    rank = _validate_rank(provider_id, item["source_rank"])
                except (KeyError, RankingError):
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
