import hashlib
import pytest

from src.publish import publish_release
from src.validate import ValidationError


def make_release():
    detail_path = (
        "releases/test-release/items/"
        + hashlib.sha256("movie:imdb:tt123".encode("utf-8")).hexdigest()[:24]
        + ".json"
    )
    return {
        "schema_version": 2,
        "release_id": "test-release",
        "generated_at": "2026-01-01T00:00:00Z",
        "ranking_version": "rrf-v1",
        "catalog_freshness": {
            "status": "fresh",
            "oldest_source_age_hours": 1.0,
            "newest_source_age_hours": 1.0,
            "snapshot_statuses": ["fresh"],
            "age_basis": "provider snapshot fetched_at",
        },
        "rows": [{
            "id": "popular_movies",
            "title": "Popular movies",
            "media_type": "movie",
            "media_kind": "movie",
            "data_updated_at": "2026-01-01T00:00:00Z",
            "status": "active",
            "configured_provider_count": 1,
            "contributing_provider_count": 1,
            "items": [{
                "id": "movie:imdb:tt123",
                "media_kind": "movie",
                "details_path": detail_path,
                "title": "Example",
                "images": {"poster": None, "backdrop": None, "logo": None},
                "metadata": {"overview": None, "genres": [], "runtime_minutes": None},
                "source_attribution": [{
                    "provider_id": "tmdb",
                    "list_id": "popular_movies",
                    "rank": 1,
                    "weight": 1.0,
                    "fetched_at": "2026-01-01T00:00:00Z",
                    "freshness": "fresh",
                }],
                "ranking": {
                    "consensus_score": 1 / 61,
                    "provider_count": 1,
                    "best_rank": 1,
                    "average_rank": 1.0,
                },
            }],
        }],
        "item_details": {
            detail_path: {
                "schema_version": 1,
                "id": "movie:imdb:tt123",
                "media_kind": "movie",
                "title": "Example",
                "release_date": "2026-01-01",
                "tmdb_full": {"credits": {"cast": [{"name": "Actor One"}]}},
                "watch_providers": {},
                "source_item": {"id": 123, "title": "Example"},
            }
        },
    }


def test_publish_creates_manifest_and_details(tmp_path):
    manifest = publish_release(make_release(), tmp_path)
    assert manifest.exists()
    release_dir = tmp_path / "v1/releases/test-release"
    assert (release_dir / "rows/popular_movies.json").exists()
    filename = hashlib.sha256("movie:imdb:tt123".encode()).hexdigest()[:24] + ".json"
    detail_path = release_dir / "items" / filename
    assert detail_path.exists()
    row = __import__("json").loads((release_dir / "rows/popular_movies.json").read_text())
    row_item = row["items"][0]
    assert row_item["details_path"].endswith(filename)
    assert "tmdb_full" not in row_item
    assert "watch_providers" not in row_item
    assert __import__("json").loads(detail_path.read_text())["tmdb_full"]["credits"]["cast"][0]["name"] == "Actor One"


def test_invalid_release_is_rejected(tmp_path):
    release = make_release()
    release["schema_version"] = 1
    with pytest.raises(ValidationError):
        publish_release(release, tmp_path)
