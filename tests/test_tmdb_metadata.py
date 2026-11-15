from datetime import datetime, timezone

from src.fetch import SourceSnapshot
from src.manifest import _images, build_release
from src.validate import validate_release


NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)


def _release(media_type, item):
    row_id = "popular-movies" if media_type == "movie" else "popular-series"
    request_id = "popular_movies" if media_type == "movie" else "popular_series"
    row = {
        "id": row_id,
        "name": "Popular",
        "type": media_type,
        "source_lists": [request_id],
    }
    snapshot = SourceSnapshot(
        request_id=request_id,
        provider_id="tmdb",
        list_id=request_id,
        media_type=media_type,
        fetched_at=NOW.isoformat(),
        items=[item],
    )
    return build_release([row], [snapshot], NOW)


def test_tmdb_movie_fields_are_normalized_and_publishable():
    release = _release(
        "movie",
        {
            "id": 101,
            "title": "Example Film",
            "release_date": "2024-05-06",
            "poster_path": "/poster.jpg",
            "backdrop_path": "/backdrop.jpg",
            "overview": "A useful synopsis.",
            "genre_ids": [28, 878],
            "vote_average": 7.8,
        },
    )

    item = release["rows"][0]["items"][0]
    assert item["year"] == 2024
    assert item["images"] == {
        "poster": "https://image.tmdb.org/t/p/w500/poster.jpg",
        "backdrop": "https://image.tmdb.org/t/p/w1280/backdrop.jpg",
        "logo": None,
    }
    assert item["metadata"]["overview"] == "A useful synopsis."
    assert item["metadata"]["genres"] == ["Action", "Science Fiction"]
    assert item["metadata"]["runtime_minutes"] is None
    assert item["ranking"] is not None
    validate_release(release)


def test_tmdb_series_first_air_date_and_tv_genres_are_normalized():
    release = _release(
        "series",
        {
            "id": 202,
            "name": "Example Series",
            "first_air_date": "2021-09-12",
            "poster_path": "/series-poster.jpg",
            "overview": "A series synopsis.",
            "genre_ids": [10759, 16],
        },
    )

    item = release["rows"][0]["items"][0]
    assert item["year"] == 2021
    assert item["metadata"]["overview"] == "A series synopsis."
    assert item["metadata"]["genres"] == ["Action & Adventure", "Animation"]
    validate_release(release)


def test_image_mapping_preserves_absolute_urls_and_rejects_invalid_paths():
    assert _images({"poster": "https://cdn.example/poster.jpg"})["poster"] == (
        "https://cdn.example/poster.jpg"
    )
    assert _images({"poster": "//cdn.example/poster.jpg"})["poster"] is None
    assert _images({"poster": "poster.jpg"})["poster"] is None


def test_existing_named_genres_and_runtime_are_preserved():
    release = _release(
        "movie",
        {
            "id": 303,
            "title": "Metadata Film",
            "genres": [{"id": 18, "name": "Drama"}, {"id": 35, "name": "Comedy"}],
            "runtime": 112,
            "poster_path": "/metadata-poster.jpg",
        },
    )

    item = release["rows"][0]["items"][0]
    assert item["metadata"]["genres"] == ["Drama", "Comedy"]
    assert item["metadata"]["runtime_minutes"] == 112
    validate_release(release)
