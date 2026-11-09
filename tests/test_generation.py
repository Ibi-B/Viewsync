from datetime import datetime, timezone

from src.fetch import SourceSnapshot
from src.manifest import build_release


def _snapshot(request_id, media_type, imdb_id, title, now):
    return SourceSnapshot(
        request_id=request_id,
        provider_id="fixture",
        list_id=request_id,
        media_type=media_type,
        fetched_at=now.isoformat(),
        items=[{"imdb_id": imdb_id, "title": title}],
    )


def test_build_release_includes_popular_new_and_upcoming_rows():
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    rows = [
        {"id": "popular-movies", "name": "Popular Movies", "type": "movie",
         "source_lists": ["popular_movies"]},
        {"id": "new-movies", "name": "New Movies", "type": "movie",
         "source_lists": ["new_movies"]},
        {"id": "upcoming-movies", "name": "Upcoming Movies", "type": "movie",
         "source_lists": ["upcoming_movies"]},
    ]
    snapshots = [
        _snapshot("popular_movies", "movie", "tt0000001", "Popular", now),
        _snapshot("new_movies", "movie", "tt0000002", "New", now),
        _snapshot("upcoming_movies", "movie", "tt0000003", "Upcoming", now),
    ]

    release = build_release(rows, snapshots, now)

    assert [row["id"] for row in release["rows"]] == [
        "popular-movies", "new-movies", "upcoming-movies"
    ]
    assert all(len(row["items"]) == 1 for row in release["rows"])
