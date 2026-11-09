import json
from datetime import datetime, timezone
from pathlib import Path

from src.fetch import SourceSnapshot
from src.manifest import build_release
from src.publish import publish_release


def _snapshot(provider_id, items):
    return SourceSnapshot(
        request_id="popular_movies",
        provider_id=provider_id,
        list_id="popular_movies",
        media_type="movie",
        fetched_at="2026-11-09T00:00:00+00:00",
        items=items,
    )


def test_build_release_merges_and_ranks_snapshot_items():
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    snapshots = [
        _snapshot(
            "provider-a",
            [
                {"imdb_id": "tt0111161", "name": "The Shawshank Redemption", "year": "1994"},
                {"imdb_id": "tt0068646", "name": "The Godfather", "year": "1972"},
            ],
        ),
        _snapshot(
            "provider-b",
            [
                {"tmdb_id": "278", "title": "The Shawshank Redemption", "release_date": "1994-09-23"},
            ],
        ),
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

    assert release["schema_version"] == 1
    assert release["release_id"] == "20261109T000000Z"
    assert len(release["rows"]) == 1

    row = release["rows"][0]
    assert row["id"] == "popular-movies"
    assert row["configured_provider_count"] == 2
    assert row["contributing_provider_count"] == 2
    assert len(row["items"]) == 2

    first = row["items"][0]
    assert first["_viewsync_id"] == "movie:imdb:tt0111161"
    assert first["ranking"]["provider_count"] == 2
    assert first["ranking"]["consensus_score"] > 0


def test_publish_release_writes_manifest_and_row_files(tmp_path: Path):
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    snapshots = [
        _snapshot(
            "provider-a",
            [
                {"imdb_id": "tt0111161", "name": "The Shawshank Redemption", "year": "1994"},
            ],
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

    release = build_release(rows, snapshots, now)
    manifest_path = publish_release(release, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["release_id"] == release["release_id"]
    assert (tmp_path / "v1" / "releases" / release["release_id"] / "manifest.json").exists()
    assert (tmp_path / "v1" / "releases" / release["release_id"] / "rows" / "popular-movies.json").exists()


def test_main_module_exposes_generation_entry_point():
    from src import main

    assert callable(main.generate_catalog)
    assert callable(main.main)
