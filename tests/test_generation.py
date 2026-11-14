from datetime import datetime, timezone

from src.fetch import SourceSnapshot, fetch_source
from src.manifest import build_release


def test_build_release_includes_configured_rows():
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    rows = [
        {
            "id": "popular-movies",
            "name": "Popular Movies",
            "type": "movie",
            "source_lists": ["popular_movies"],
            "extra": [],
            "date_field": None,
            "date_mode": "none",
        },
        {
            "id": "new-movies",
            "name": "New Movies",
            "type": "movie",
            "source_lists": ["new_movies"],
            "extra": [],
            "date_field": "release_date",
            "date_mode": "recent",
        },
        {
            "id": "upcoming-movies",
            "name": "Upcoming Movies",
            "type": "movie",
            "source_lists": ["upcoming_movies"],
            "extra": [],
            "date_field": "release_date",
            "date_mode": "future",
        },
    ]

    snapshots = [
        SourceSnapshot(
            request_id="popular_movies",
            provider_id="tmdb",
            list_id="popular_movies",
            media_type="movie",
            fetched_at=now.isoformat(),
            items=[{"id": 1, "title": "Popular Movie", "poster_path": "/poster.jpg"}],
        ),
        SourceSnapshot(
            request_id="new_movies",
            provider_id="tmdb",
            list_id="new_movies",
            media_type="movie",
            fetched_at=now.isoformat(),
            items=[{"id": 2, "title": "New Movie", "poster_path": "/poster.jpg"}],
        ),
        SourceSnapshot(
            request_id="upcoming_movies",
            provider_id="tmdb",
            list_id="upcoming_movies",
            media_type="movie",
            fetched_at=now.isoformat(),
            items=[{"id": 3, "title": "Upcoming Movie", "poster_path": "/poster.jpg"}],
        ),
    ]

    release = build_release(rows, snapshots, now)

    assert [row["id"] for row in release["rows"]] == [
        "popular-movies",
        "new-movies",
        "upcoming-movies",
    ]


def test_fetch_source_uses_provider_config(monkeypatch):
    request = {
        "id": "popular_movies",
        "type": "movie",
        "providers": {
            "tmdb": {
                "list_id": "popular_movies",
                "media_type": "movie",
                "max_items": 10,
            }
        },
    }

    monkeypatch.setenv("TMDB_API_KEY", "test-only-key")
    monkeypatch.setattr(
        "src.fetch._get_json",
        lambda url, params=None, headers=None, raw_responses=None: {"results": [{"id": 1, "title": "Popular Movie"}]},
    )

    items = fetch_source(request, "tmdb")

    assert len(items) <= 10
    assert items[0]["title"] == "Popular Movie"
