import copy
import hashlib
import json

import pytest

from src.publish import publication_size_report, publish_release
from src.validate import ValidationError


def _detail_path(document):
    canonical = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"details/{hashlib.sha256(canonical).hexdigest()}.json"


def _hydrate_shards(value, root):
    if isinstance(value, dict):
        marker = value.get("__viewsync_shard_v1__")
        if isinstance(marker, dict):
            kind = marker.get("kind")
            if kind == "root":
                return _hydrate_shards(marker["payload"], root)
            parts = [
                _hydrate_shards(
                    json.loads((root / part).read_text(encoding="utf-8"))["payload"],
                    root,
                )
                for part in marker.get("parts", [])
            ]
            if kind == "map":
                merged = {}
                for part in parts:
                    merged.update(part)
                return merged
            if kind == "list":
                return [entry for part in parts for entry in part]
            if kind == "string":
                return "".join(parts)
            raise AssertionError(f"Unknown shard kind: {kind}")
        return {key: _hydrate_shards(child, root) for key, child in value.items()}
    if isinstance(value, list):
        return [_hydrate_shards(child, root) for child in value]
    return value


def make_release():
    detail = {
        "schema_version": 1,
        "id": "movie:imdb:tt123",
        "media_kind": "movie",
        "title": "Example",
        "release_date": "2026-01-01",
        "tmdb_full": {"credits": {"cast": [{"name": "Actor One"}]}},
        "watch_providers": {},
        "source_item": {"id": 123, "title": "Example"},
    }
    detail_path = _detail_path(detail)
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
        "item_details": {detail_path: detail},
    }


def test_publish_creates_manifest_and_content_addressed_details(tmp_path):
    manifest = publish_release(make_release(), tmp_path)
    assert manifest.exists()
    release_dir = tmp_path / "v1/releases/test-release"
    assert (release_dir / "rows/popular_movies.json").exists()
    row = json.loads((release_dir / "rows/popular_movies.json").read_text())
    row_item = row["items"][0]
    assert row_item["details_path"].startswith("details/")
    detail_path = manifest.parent / row_item["details_path"]
    assert detail_path.exists()
    assert "tmdb_full" not in row_item
    assert "watch_providers" not in row_item
    detail = json.loads(detail_path.read_text())
    assert detail["tmdb_full"]["credits"]["cast"][0]["name"] == "Actor One"


def test_unchanged_detail_path_is_reused_across_release_generations(tmp_path):
    first = make_release()
    second = copy.deepcopy(first)
    second["release_id"] = "next-release"
    second["generated_at"] = "2026-01-01T12:00:00Z"

    publish_release(first, tmp_path)
    publish_release(second, tmp_path)

    first_path = first["rows"][0]["items"][0]["details_path"]
    second_path = second["rows"][0]["items"][0]["details_path"]
    assert first_path == second_path


def test_invalid_release_is_rejected(tmp_path):
    release = make_release()
    release["schema_version"] = 1
    with pytest.raises(ValidationError):
        publish_release(release, tmp_path)


def test_large_catalogue_keeps_full_item_data_in_individual_files(tmp_path):
    release = make_release()
    source = release["rows"][0]["items"][0]
    base_item_detail = next(iter(release["item_details"].values()))
    row_items = []
    details = {}

    for index in range(100):
        media_id = f"movie:tmdb:{index + 1}"
        row_item = copy.deepcopy(source)
        row_item.update(
            id=media_id,
            title=f"Media title {index + 1}",
        )
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
        detail_path = _detail_path(detail)
        row_item["details_path"] = detail_path
        row_items.append(row_item)
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
    first_path = row_payload["items"][0]["details_path"]
    first_detail = json.loads((root / first_path).read_text())
    assert len(first_detail["tmdb_full"]["overview"]) == 100_000
    assert len(first_detail["tmdb_full"]["credits"]["cast"]) == 40
    assert set(first_detail["watch_providers"]["SE"]) == {
        "flatrate", "rent", "buy", "free", "ads"
    }


def test_oversized_detail_is_sharded_and_reassembled_without_loss(tmp_path):
    release = make_release()
    row_item = release["rows"][0]["items"][0]
    old_path = row_item["details_path"]
    detail = release["item_details"].pop(old_path)
    huge_cast = "演员-" * 1_500_000
    detail["tmdb_full"] = {
        "credits": {"cast": [{"name": huge_cast}, {"name": "Second actor"}]},
        "images": {"backdrops": [{"file_path": f"/backdrop-{index}.jpg"} for index in range(200)]},
        "translations": {"data": [{"title": f"Locale {index}"} for index in range(100)]},
    }
    new_path = _detail_path(detail)
    row_item["details_path"] = new_path
    release["item_details"][new_path] = detail

    manifest = publish_release(release, tmp_path)
    root = manifest.parent
    root_file = root / new_path
    assert root_file.stat().st_size < 4 * 1024 * 1024

    raw = json.loads(root_file.read_text(encoding="utf-8"))
    rebuilt = _hydrate_shards(raw, root)
    assert rebuilt["tmdb_full"]["credits"]["cast"][0]["name"] == huge_cast
    assert rebuilt["tmdb_full"]["credits"]["cast"][1]["name"] == "Second actor"
    assert len(rebuilt["tmdb_full"]["images"]["backdrops"]) == 200
    assert len(rebuilt["tmdb_full"]["translations"]["data"]) == 100

    sizes = publication_size_report(tmp_path)
    assert sizes["files_over_limit"] == []
    assert sizes["maximum_file_bytes"] < 4 * 1024 * 1024
