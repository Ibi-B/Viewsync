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



def test_new_and_upcoming_rows_are_disjoint_at_the_date_boundary():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    rows = [
        {
            "id": "new-movies", "name": "New Movies", "type": "movie",
            "source_lists": ["new_movies"], "date_field": "release_date", "date_mode": "recent",
        },
        {
            "id": "upcoming-movies", "name": "Upcoming Movies", "type": "movie",
            "source_lists": ["upcoming_movies"], "date_field": "release_date", "date_mode": "future",
        },
    ]
    snapshots = [
        SourceSnapshot(
            request_id="new_movies", provider_id="tmdb", list_id="new_movies",
            media_type="movie", fetched_at=now.isoformat(),
            items=[
                {"id": 1, "title": "Yesterday", "release_date": "2026-11-20"},
                {"id": 2, "title": "Today", "release_date": "2026-11-21"},
            ],
        ),
        SourceSnapshot(
            request_id="upcoming_movies", provider_id="tmdb", list_id="upcoming_movies",
            media_type="movie", fetched_at=now.isoformat(),
            items=[
                {"id": 2, "title": "Today", "release_date": "2026-11-21"},
                {"id": 3, "title": "Tomorrow", "release_date": "2026-11-22"},
            ],
        ),
    ]

    release = build_release(rows, snapshots, now)
    by_row = {row["id"]: {item["id"] for item in row["items"]} for row in release["rows"]}

    assert by_row["new-movies"] == {"movie:tmdb:1"}
    assert by_row["upcoming-movies"] == {"movie:tmdb:2", "movie:tmdb:3"}
    assert by_row["new-movies"].isdisjoint(by_row["upcoming-movies"])
