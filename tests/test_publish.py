from src.publish import publish_release
from src.validate import ValidationError


def make_release():
    return {
        "schema_version": 1,
        "release_id": "test-release",
        "published_at": "2026-01-01T00:00:00Z",
        "ranking_version": "rrf-v1",
        "rows": [
            {
                "id": "popular_movies",
                "title": "Popular movies",
                "media_type": "movie",
                "data_updated_at": "2026-01-01T00:00:00Z",
                "status": "fresh",
                "configured_provider_count": 1,
                "contributing_provider_count": 1,
                "items": [
                    {
                        "id": "movie:imdb:tt123",
                        "type": "movie",
                        "title": "Example",
                    }
                ],
            }
        ],
    }


def test_publish_creates_manifest_and_details(tmp_path):
    manifest = publish_release(make_release(), tmp_path)
    assert manifest.exists()
    assert (tmp_path / "v1/releases/test-release/rows/popular_movies.json").exists()
    assert (tmp_path / "v1/releases/test-release/items/movie_imdb_tt123.json").exists()


def test_invalid_release_is_rejected(tmp_path):
    release = make_release()
    release["schema_version"] = 2

    try:
        publish_release(release, tmp_path)
    except ValidationError:
        pass
    else:
        raise AssertionError("Expected ValidationError")
