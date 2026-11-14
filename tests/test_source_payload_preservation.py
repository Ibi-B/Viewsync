import json
from datetime import datetime, timezone

from src.fetch import SourceSnapshot, load_snapshot, save_snapshot
from src.state import preserve_last_good_release, persist_snapshots, restore_snapshots


def test_snapshot_round_trip_preserves_full_raw_provider_payload(tmp_path):
    raw_payloads = [
        {
            "page": 1,
            "total_pages": 2,
            "results": [{"id": 1, "title": "A"}, "unstructured-record"],
            "provider_metadata": {"request_id": "upstream-123"},
        },
        {
            "page": 2,
            "total_pages": 2,
            "results": [{"id": 2, "title": "B"}],
            "provider_metadata": {"request_id": "upstream-123"},
        },
    ]
    snapshot = SourceSnapshot(
        request_id="popular_movies",
        provider_id="tmdb",
        list_id="popular_movies",
        media_type="movie",
        fetched_at=datetime(2026, 11, 14, tzinfo=timezone.utc).isoformat(),
        items=[{"id": 1, "title": "A"}],
        raw_payloads=raw_payloads,
    )

    path = save_snapshot(snapshot, tmp_path)
    restored = load_snapshot(path)

    assert restored.items == snapshot.items
    assert restored.raw_payloads == raw_payloads
    assert restored.raw_payloads[0]["results"][1] == "unstructured-record"
    assert restored.raw_payloads[1]["page"] == 2


def test_legacy_snapshot_without_raw_payloads_remains_readable(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({
        "request_id": "popular_movies",
        "provider_id": "tmdb",
        "list_id": "popular_movies",
        "media_type": "movie",
        "fetched_at": "2026-11-14T00:00:00+00:00",
        "items": [{"id": 1}],
    }), encoding="utf-8")

    restored = load_snapshot(path)

    assert restored.items == [{"id": 1}]
    assert restored.raw_payloads == []


def test_preserving_last_good_release_never_overwrites_existing_copy(tmp_path):
    state_dir = tmp_path / "state"
    releases_dir = tmp_path / "dist" / "v1" / "releases"
    source = releases_dir / "release-1"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text("original", encoding="utf-8")
    marker = state_dir / "last-good-release" / "release.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"release_id": "release-1"}), encoding="utf-8")

    first_copy = releases_dir / "release-1-preserved"
    first_copy.mkdir()
    (first_copy / "manifest.json").write_text("keep-me", encoding="utf-8")

    assert preserve_last_good_release(state_dir, tmp_path / "dist") is True
    assert (first_copy / "manifest.json").read_text(encoding="utf-8") == "keep-me"
    assert (releases_dir / "release-1-preserved-1" / "manifest.json").read_text(
        encoding="utf-8"
    ) == "original"



def test_persisting_new_fetch_keeps_earlier_snapshot_version(tmp_path):
    earlier = SourceSnapshot(
        request_id="popular_movies",
        provider_id="tmdb",
        list_id="popular_movies",
        media_type="movie",
        fetched_at="2026-11-13T00:00:00+00:00",
        items=[{"id": 1}],
        raw_payloads=[{"results": [{"id": 1}]}],
    )
    later = SourceSnapshot(
        request_id="popular_movies",
        provider_id="tmdb",
        list_id="popular_movies",
        media_type="movie",
        fetched_at="2026-11-14T00:00:00+00:00",
        items=[{"id": 2}],
        raw_payloads=[{"results": [{"id": 2}]}],
    )

    persist_snapshots([earlier], tmp_path)
    persist_snapshots([later], tmp_path)

    stored = list((tmp_path / "source-snapshots").glob("*.json"))
    restored = restore_snapshots(tmp_path)

    assert len(stored) == 2
    assert restored["popular_movies:tmdb:popular_movies"].items == [{"id": 2}]
    assert sorted(json.loads(path.read_text(encoding="utf-8"))["items"][0]["id"] for path in stored) == [1, 2]
