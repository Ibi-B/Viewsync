from datetime import datetime, timedelta, timezone

import pytest

from src.fetch import SourceSnapshot
from src.manifest import build_release
from src.validate import ValidationError, validate_release


def _snapshot(provider_id, fetched_at, items):
    return SourceSnapshot(
        request_id="popular_movies",
        provider_id=provider_id,
        list_id="popular_movies",
        media_type="movie",
        fetched_at=fetched_at,
        items=items,
    )


def _item(media_id, title):
    return {
        "imdb_id": media_id,
        "title": title,
        "year": "1994",
        "poster": "https://example.com/poster.jpg",
    }


def test_catalog_freshness_includes_real_source_ages():
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    snapshots = [
        _snapshot("fresh", (now - timedelta(hours=2)).isoformat(), []),
        _snapshot("old", (now - timedelta(hours=20)).isoformat(), []),
    ]
    rows = [
        {
            "id": "popular-movies",
            "name": "Popular Movies",
            "type": "movie",
            "source_lists": ["popular_movies"],
        }
    ]

    release = build_release(rows, snapshots, now)
    freshness = release["catalog_freshness"]

    assert freshness["oldest_source_age_hours"] == 20.0
    assert freshness["newest_source_age_hours"] == 2.0
    assert freshness["status"] == "mixed"


def test_provider_weights_are_used_in_ranking_and_attribution():
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    snapshots = [
        _snapshot(
            "provider-a",
            now.isoformat(),
            [_item("tt0111161", "The Shawshank Redemption")],
        )
    ]
    rows = [
        {
            "id": "popular-movies",
            "name": "Popular Movies",
            "type": "movie",
            "source_lists": ["popular_movies"],
        }
    ]

    release = build_release(
        rows,
        snapshots,
        now,
        provider_weights={"provider-a": 2.5},
    )
    item = release["rows"][0]["items"][0]

    assert item["source_attribution"][0]["weight"] == 2.5
    assert item["ranking"]["consensus_score"] > 0


def test_live_tv_and_radio_rows_are_not_generated_by_viewsync():
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    snapshots = [
        _snapshot(
            "provider-a",
            now.isoformat(),
            [_item("tt0111161", "The Shawshank Redemption")],
        )
    ]
    rows = [
        {
            "id": "live-tv",
            "name": "Live TV",
            "media_kind": "live_tv",
            "source_lists": ["popular_movies"],
        },
        {
            "id": "radio",
            "name": "Radio",
            "media_kind": "radio",
            "source_lists": ["popular_movies"],
        },
    ]

    release = build_release(rows, snapshots, now)

    assert release["rows"] == []


def test_empty_source_attribution_is_rejected():
    release = build_release(
        [
            {
                "id": "popular-movies",
                "name": "Popular Movies",
                "type": "movie",
                "source_lists": ["popular_movies"],
            }
        ],
        [
            _snapshot(
                "provider-a",
                datetime(2026, 11, 9, tzinfo=timezone.utc).isoformat(),
                [_item("tt0111161", "The Shawshank Redemption")],
            )
        ],
        datetime(2026, 11, 9, tzinfo=timezone.utc),
    )
    release["rows"][0]["items"][0]["source_attribution"] = []

    with pytest.raises(ValidationError):
        validate_release(release)


def test_invalid_attribution_rank_or_weight_is_rejected():
    release = build_release(
        [
            {
                "id": "popular-movies",
                "name": "Popular Movies",
                "type": "movie",
                "source_lists": ["popular_movies"],
            }
        ],
        [
            _snapshot(
                "provider-a",
                datetime(2026, 11, 9, tzinfo=timezone.utc).isoformat(),
                [_item("tt0111161", "The Shawshank Redemption")],
            )
        ],
        datetime(2026, 11, 9, tzinfo=timezone.utc),
    )

    release["rows"][0]["items"][0]["source_attribution"][0]["rank"] = 0
    with pytest.raises(ValidationError):
        validate_release(release)

    release["rows"][0]["items"][0]["source_attribution"][0]["rank"] = 1
    release["rows"][0]["items"][0]["source_attribution"][0]["weight"] = 0
    with pytest.raises(ValidationError):
        validate_release(release)
