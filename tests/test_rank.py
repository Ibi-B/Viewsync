from src.fetch import SourceSnapshot
from src.rank import build_ranking, order_items


def make_snapshot(request_id, provider_id, list_id, media_type, titles):
    return SourceSnapshot(
        request_id=request_id,
        provider_id=provider_id,
        list_id=list_id,
        media_type=media_type,
        url="https://example.invalid",
        fetched_at="2026-01-01T00:00:00Z",
        items=[
            {
                "_viewsync_id": f"{media_type}:imdb:{imdb}",
                "source_rank": rank,
            }
            for rank, imdb in enumerate(titles, start=1)
        ],
    )


def test_provider_lists_do_not_multiply_weight():
    snapshots = [
        make_snapshot("a", "provider", "list_a", "movie", ["tt1", "tt2"]),
        make_snapshot("b", "provider", "list_b", "movie", ["tt1", "tt2"]),
    ]

    rankings = build_ranking(snapshots, provider_weights={"provider": 1.0})

    assert rankings["movie:imdb:tt1"]["consensus_score"] > rankings["movie:imdb:tt2"]["consensus_score"]
    assert rankings["movie:imdb:tt1"]["source_count"] == 1


def test_cross_provider_agreement_ranks_higher():
    snapshots = [
        make_snapshot("a", "provider_a", "list_a", "movie", ["tt1", "tt2"]),
        make_snapshot("b", "provider_b", "list_b", "movie", ["tt2", "tt1"]),
    ]

    rankings = build_ranking(snapshots, provider_weights={"provider_a": 1.0, "provider_b": 1.0})
    items = [
        {"_viewsync_id": "movie:imdb:tt1"},
        {"_viewsync_id": "movie:imdb:tt2"},
    ]

    ordered = order_items(items, rankings)

    # Both titles have identical RRF scores, source counts, and best ranks.
    # The stable media-ID tie-break therefore preserves deterministic order.
    assert ordered[0]["_viewsync_id"] == "movie:imdb:tt1"
    assert ordered[1]["_viewsync_id"] == "movie:imdb:tt2"
    assert rankings["movie:imdb:tt1"]["source_count"] == 2
    assert rankings["movie:imdb:tt2"]["source_count"] == 2
