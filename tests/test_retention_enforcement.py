import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.fetch import SourceSnapshot
from src.main import generate_catalog
from src.state import (
    persist_snapshots,
    prune_expired_tmdb_source_snapshots,
    select_snapshots,
    snapshot_status,
)


def _snapshot(provider_id, fetched_at, items=None):
    return SourceSnapshot(
        request_id="popular_movies",
        provider_id=provider_id,
        list_id="popular_movies",
        media_type="movie",
        fetched_at=fetched_at,
        items=items or [],
    )


def test_snapshot_status_uses_retention_tiers():
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    policy = {}

    assert snapshot_status(_snapshot("a", "2026-11-09T00:00:00+00:00"), policy, now) == "fresh"
    assert snapshot_status(
        _snapshot("a", "2026-11-07T00:00:00+00:00"), policy, now
    ) == "retained_full"
    assert snapshot_status(
        _snapshot("a", "2026-11-05T00:00:00+00:00"), policy, now
    ) == "retained_declining"
    assert snapshot_status(
        _snapshot("a", "2026-11-01T00:00:00+00:00"), policy, now
    ) == "expired"


def test_select_snapshots_excludes_expired_snapshots():
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    fresh = _snapshot("fresh", (now - timedelta(hours=1)).isoformat())
    retained = _snapshot("retained", (now - timedelta(hours=24)).isoformat())
    expired = _snapshot("expired", (now - timedelta(hours=120)).isoformat())

    usable, expired_snapshots = select_snapshots([fresh, retained, expired], {}, now)

    assert usable == [fresh, retained]
    assert expired_snapshots == [expired]


def test_durable_tmdb_source_snapshots_keep_ids_but_not_descriptive_metadata(tmp_path):
    from src.fetch import load_snapshot

    now = datetime(2026, 11, 22, tzinfo=timezone.utc)
    tmdb = SourceSnapshot(
        request_id="popular_movies",
        provider_id="tmdb",
        list_id="popular_movies",
        media_type="movie",
        fetched_at=now.isoformat(),
        items=[{
            "id": 123,
            "title": "Example title",
            "overview": "Descriptive overview",
            "poster_path": "/poster.jpg",
            "vote_count": 900,
            "release_date": "2026-11-20",
        }],
        raw_payloads=[{
            "results": [{
                "id": 123,
                "title": "Example title",
                "overview": "Raw overview",
            }]
        }],
    )
    trakt = SourceSnapshot(
        request_id="trending_movies",
        provider_id="trakt",
        list_id="trending_movies",
        media_type="movie",
        fetched_at=now.isoformat(),
        items=[{"title": "Trakt item", "overview": "Non-TMDB snapshot"}],
        raw_payloads=[{"data": "retained"}],
    )

    persist_snapshots([tmdb, trakt], tmp_path)
    files = list((tmp_path / "source-snapshots").glob("*.json"))
    saved = [load_snapshot(path) for path in files]
    saved_tmdb = next(item for item in saved if item.provider_id == "tmdb")
    saved_trakt = next(item for item in saved if item.provider_id == "trakt")

    assert saved_tmdb.items == [{"id": 123}]
    assert saved_tmdb.raw_payloads == []
    assert tmdb.items[0]["overview"] == "Descriptive overview"
    assert saved_trakt.items[0]["overview"] == "Non-TMDB snapshot"
    assert saved_trakt.raw_payloads == [{"data": "retained"}]


def test_tmdb_source_snapshot_history_is_purged_after_150_days_only(tmp_path):
    now = datetime(2026, 11, 22, tzinfo=timezone.utc)
    state_dir = tmp_path / "state"
    old_tmdb = _snapshot(
        "tmdb",
        (now - timedelta(days=151)).isoformat(),
        items=[{"id": 1, "title": "Old TMDB title", "overview": "Old metadata"}],
    )
    recent_tmdb = _snapshot(
        "tmdb",
        (now - timedelta(days=149)).isoformat(),
        items=[{"id": 2, "title": "Retained TMDB title", "overview": "Metadata"}],
    )
    old_trakt = SourceSnapshot(
        request_id="trending_movies",
        provider_id="trakt",
        list_id="trending_movies",
        media_type="movie",
        fetched_at=(now - timedelta(days=400)).isoformat(),
        items=[{"title": "Trakt item"}],
    )
    persist_snapshots([old_tmdb, recent_tmdb, old_trakt], state_dir)
    snapshot_dir = state_dir / "source-snapshots"
    before = list(snapshot_dir.glob("*.json"))

    removed = prune_expired_tmdb_source_snapshots(state_dir, now)
    after = list(snapshot_dir.glob("*.json"))

    assert len(removed) == 1
    assert len(after) == 2
    remaining = [json.loads(path.read_text(encoding="utf-8")) for path in after]
    assert {item["provider_id"] for item in remaining} == {"tmdb", "trakt"}
    assert any(
        item["provider_id"] == "tmdb" and item["items"][0]["id"] == 2
        for item in remaining
    )
    assert any(item["provider_id"] == "trakt" for item in remaining)
    assert len(before) == 3


def test_malformed_or_unknown_age_snapshot_is_not_pruned(tmp_path):
    now = datetime(2026, 11, 22, tzinfo=timezone.utc)
    snapshot_dir = tmp_path / "state" / "source-snapshots"
    snapshot_dir.mkdir(parents=True)
    malformed = snapshot_dir / "malformed.json"
    malformed.write_text("{not-json", encoding="utf-8")

    removed = prune_expired_tmdb_source_snapshots(snapshot_dir.parent, now)

    assert removed == []
    assert malformed.exists()


def test_generate_catalog_records_diagnostics_and_current_pointer(tmp_path, monkeypatch):
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    items = [
        {
            "imdb_id": "tt0111161",
            "title": "The Shawshank Redemption",
            "year": "1994",
        }
    ]

    def fake_fetch_source(request, provider, today=None, raw_responses=None):
        if provider == "tmdb" and request["id"] == "popular_movies":
            raise RuntimeError("upstream unavailable")
        if raw_responses is not None:
            raw_responses.append({"results": items, "source_meta": {"complete": True}})
        return items

    monkeypatch.setattr("src.main.fetch_source", fake_fetch_source)
    monkeypatch.setattr("src.tmdb_enrichment._load_previous_region_directory", lambda: {})
    monkeypatch.setattr("src.main.load_previous_detail_index", lambda **kwargs: {})

    release = generate_catalog(
        config_dir="catalog-config",
        output_dir=tmp_path,
        now=now,
    )

    report_path = tmp_path / "state" / "generation-report.json"
    current_path = tmp_path / "v1" / "current.json"
    last_good_path = tmp_path / "state" / "last-good-release" / "release.json"

    assert report_path.exists()
    assert current_path.exists()
    assert last_good_path.exists()
    assert release["release_id"] == "20261109T000000Z"

    report = __import__("json").loads(report_path.read_text(encoding="utf-8"))
    assert report["fetch_failure_count"] >= 1
    assert report["usable_snapshot_count"] >= 1

    current = __import__("json").loads(current_path.read_text(encoding="utf-8"))
    assert current["release_id"] == release["release_id"]
    assert current["status"] == "current"


def test_generate_catalog_refuses_when_all_snapshots_expire(tmp_path, monkeypatch):
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    state_dir = tmp_path / "state"
    requests = json.loads(
        (Path("catalog-config") / "requests.json").read_text(encoding="utf-8")
    )

    expired_snapshots = []
    for request in requests:
        provider_id, provider_config = next(iter(request["providers"].items()))
        expired_snapshots.append(
            SourceSnapshot(
                request_id=request["id"],
                provider_id=provider_id,
                list_id=provider_config["list_id"],
                media_type=provider_config["media_type"],
                fetched_at=(now - timedelta(hours=120)).isoformat(),
                items=[],
            )
        )
    persist_snapshots(expired_snapshots, state_dir)

    def fake_fetch_source(request, provider, today=None, raw_responses=None):
        raise RuntimeError("upstream unavailable")

    monkeypatch.setattr("src.main.fetch_source", fake_fetch_source)
    monkeypatch.setattr("src.tmdb_enrichment._load_previous_region_directory", lambda: {})
    monkeypatch.setattr("src.main.load_previous_detail_index", lambda **kwargs: {})

    with pytest.raises(ValueError, match="All provider snapshots have expired"):
        generate_catalog(
            config_dir="catalog-config",
            output_dir=tmp_path,
            now=now,
        )

    report = json.loads(
        (state_dir / "generation-report.json").read_text(encoding="utf-8")
    )
    assert report["usable_snapshot_count"] == 0
    assert report["expired_snapshot_count"] == len(expired_snapshots)
