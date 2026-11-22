import copy
import hashlib
import json
import pytest

from src.publish import publication_size_report, publish_release
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



def test_large_catalogue_keeps_full_item_data_in_individual_files(tmp_path):
    release = make_release()
    source = release["rows"][0]["items"][0]
    base_detail_path = source["details_path"]
    base_item_detail = release["item_details"].pop(base_detail_path)
    row_items = []
    details = {}

    for index in range(100):
        media_id = f"movie:tmdb:{index + 1}"
        digest = hashlib.sha256(media_id.encode("utf-8")).hexdigest()[:24]
        detail_path = f"releases/test-release/items/{digest}.json"
        row_item = copy.deepcopy(source)
        row_item.update(
            id=media_id,
            title=f"Media title {index + 1}",
            details_path=detail_path,
        )
        row_items.append(row_item)
        detail = copy.deepcopy(base_item_detail)
        detail.update(
            id=media_id,
            title=f"Media title {index + 1}",
            tmdb_full={
                "id": index + 1,
                "overview": "A" * 100_000,
                "credits": {"cast": [{"name": f"Cast member {n}"} for n in range(40)]},
                "translations": {"payload": "B" * 2_000},
                "images": {"backdrops": [{"file_path": f"/backdrop-{n}.jpg"} for n in range(40)]},
            },
            watch_providers={
                "SE": {
                    "flatrate": [{"provider_id": 8, "provider_name": "Netflix"}],
                    "rent": [{"provider_id": 2, "provider_name": "Apple TV"}],
                    "buy": [{"provider_id": 3, "provider_name": "Store"}],
                    "free": [{"provider_id": 4, "provider_name": "Free"}],
                    "ads": [{"provider_id": 5, "provider_name": "Ads"}],
                },
            },
        )
        details[detail_path] = detail

    release["rows"][0]["items"] = row_items
    release["item_details"] = details
    manifest = publish_release(release, tmp_path)
    root = manifest.parent
    row_path = root / json.loads(manifest.read_text())["rows"][0]["path"]
    row_payload = json.loads(row_path.read_text())
    row_bytes = row_path.stat().st_size
    size_report = publication_size_report(tmp_path)

    assert len(row_payload["items"]) == 100
    assert row_bytes < 5 * 1024 * 1024
    assert all("tmdb_full" not in item for item in row_payload["items"])
    assert size_report["json_file_count"] >= 102
    assert size_report["maximum_file_bytes"] < 4 * 1024 * 1024
    assert size_report["total_bytes"] > 10_000_000
    assert size_report["files_over_limit"] == []
    # The complete detail data is still present; only the list row is slim.
    first_path = row_payload["items"][0]["details_path"]
    first_detail = json.loads((root / first_path).read_text())
    assert len(first_detail["tmdb_full"]["overview"]) == 100_000
    assert len(first_detail["tmdb_full"]["credits"]["cast"]) == 40
    assert set(first_detail["watch_providers"]["SE"]) == {
        "flatrate", "rent", "buy", "free", "ads"
    }
