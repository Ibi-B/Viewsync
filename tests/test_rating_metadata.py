from datetime import datetime, timezone

from src.fetch import SourceSnapshot
from src.manifest import build_release
from src.merge_metadata import merge_item, rating_number


def test_normalizes_imdb_and_tmdb_ratings_with_provenance():
    item = merge_item(
        "movie",
        None,
        {
            "imdb_id": "tt0111161",
            "tmdb_id": "278",
            "title": "The Shawshank Redemption",
            "imdbRating": "9.3",
            "vote_average": 8.7,
        },
        "tmdb",
    )

    assert item["ratings"] == {
        "imdb": {"value": 9.3, "scale": 10},
        "tmdb": {"value": 8.7, "scale": 10},
    }
    assert item["rating"] == 9.3
    assert item["rating_source"] == "imdb"


def test_boolean_is_not_accepted_as_a_rating():
    assert rating_number(True) is None


def test_release_metadata_exposes_ratings_for_home_cards():
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    snapshot = SourceSnapshot(
        request_id="popular_movies",
        provider_id="tmdb",
        list_id="popular_movies",
        media_type="movie",
        fetched_at=now.isoformat(),
        items=[
            {
                "imdb_id": "tt0111161",
                "tmdb_id": "278",
                "title": "The Shawshank Redemption",
                "imdbRating": 9.3,
                "vote_average": 8.7,
            }
        ],
    )
    release = build_release(
        [{"id": "popular-movies", "name": "Popular Movies", "type": "movie",
          "source_lists": ["popular_movies"]}],
        [snapshot],
        now,
    )
    metadata = release["rows"][0]["items"][0]["metadata"]

    assert metadata["rating"] == 9.3
    assert metadata["rating_source"] == "imdb"
    assert metadata["ratings"]["tmdb"] == {"value": 8.7, "scale": 10}
