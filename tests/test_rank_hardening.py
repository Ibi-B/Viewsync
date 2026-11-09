import math

import pytest

from src.fetch import SourceSnapshot
from src.rank import RankingError, build_ranking, order_items, rrf_score


def _snapshot(provider_id, request_id, list_id, items):
    return SourceSnapshot(
        request_id=request_id,
        provider_id=provider_id,
        list_id=list_id,
        media_type="movie",
        fetched_at="2026-11-09T00:00:00+00:00",
        items=items,
    )


def _item(media_id, rank):
    return {"_viewsync_id": media_id, "source_rank": rank}


def test_rrf_score_rejects_non_positive_k():
    with pytest.raises(RankingError):
        rrf_score([1], k=0)

    with pytest.raises(RankingError):
        rrf_score([1], k=-1)


def test_rrf_score_rejects_invalid_weight():
    with pytest.raises(RankingError):
        rrf_score([1], provider_weight=0)

    with pytest.raises(RankingError):
        rrf_score([1], provider_weight=-1)

    with pytest.raises(RankingError):
        rrf_score([1], provider_weight=math.inf)

    with pytest.raises(RankingError):
        rrf_score([1], provider_weight=math.nan)


def test_rrf_score_rejects_invalid_rank():
    with pytest.raises(RankingError):
        rrf_score([0])

    with pytest.raises(RankingError):
        rrf_score([-1])


def test_duplicate_provider_snapshot_does_not_change_score():
    snapshot = _snapshot(
        "provider-a",
        "popular_movies",
        "popular_movies",
        [_item("movie:1", 1)],
    )
    duplicate = _snapshot(
        "provider-a",
        "popular_movies",
        "popular_movies",
        [_item("movie:1", 1)],
    )

    once = build_ranking([snapshot])
    twice = build_ranking([snapshot, duplicate])

    assert once["movie:1"]["consensus_score"] == twice["movie:1"]["consensus_score"]
    assert once["movie:1"]["source_count"] == 1
    assert twice["movie:1"]["source_count"] == 1


def test_malformed_rank_is_skipped_without_crashing():
    snapshot = _snapshot(
        "provider-a",
        "popular_movies",
        "popular_movies",
        [
            _item("movie:1", 1),
            {"_viewsync_id": "movie:2", "source_rank": "not-a-number"},
            {"_viewsync_id": "movie:3"},
        ],
    )

    rankings = build_ranking([snapshot])

    assert "movie:1" in rankings
    assert "movie:2" not in rankings
    assert "movie:3" not in rankings


def test_invalid_provider_weight_is_rejected():
    snapshot = _snapshot(
        "provider-a",
        "popular_movies",
        "popular_movies",
        [_item("movie:1", 1)],
    )

    with pytest.raises(RankingError):
        build_ranking([snapshot], provider_weights={"provider-a": 0})


def test_order_items_uses_stable_documented_ordering():
    rankings = {
        "movie:high": {
            "consensus_score": 0.08,
            "source_count": 2,
            "best_rank": 1,
        },
        "movie:wide": {
            "consensus_score": 0.08,
            "source_count": 3,
            "best_rank": 4,
        },
        "movie:low": {
            "consensus_score": 0.01,
            "source_count": 1,
            "best_rank": 2,
        },
    }
    items = [
        {"_viewsync_id": "movie:low"},
        {"_viewsync_id": "movie:wide"},
        {"_viewsync_id": "movie:high"},
    ]

    ordered = order_items(items, rankings)

    assert [item["_viewsync_id"] for item in ordered] == [
        "movie:wide",
        "movie:high",
        "movie:low",
    ]
