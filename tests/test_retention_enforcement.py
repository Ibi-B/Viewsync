from datetime import datetime, timedelta, timezone

import pytest

from src.fetch import SourceSnapshot
from src.main import generate_catalog
from src.state import select_snapshots, snapshot_status


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


def test_generate_catalog_records_diagnostics_and_current_pointer(tmp_path, monkeypatch):
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    items = [
        {
            "imdb_id": "tt0111161",
            "title": "The Shawshank Redemption",
            "year": "1994",
        }
    ]

    def fake_fetch_source(request, provider, today=None):
        if request.get("id") == "new_movies":
            raise RuntimeError("upstream unavailable")
        return items

    monkeypatch.setattr("src.main.fetch_source", fake_fetch_source)

    release = generate_catalog(
        config_dir="catalog-config",
        output_dir=tmp_path,
        now=now,
    )

    report_path = tmp_path / "state" / "generation-report.json"
    current_path = tmp_path / "v1" / "current.json"

    assert report_path.exists()
    assert current_path.exists()
    assert release["release_id"] == "20261109T000000Z"

    report = __import__("json").loads(report_path.read_text(encoding="utf-8"))
    assert report["fetch_failure_count"] >= 1
    assert report["usable_snapshot_count"] >= 1

    current = __import__("json").loads(current_path.read_text(encoding="utf-8"))
    assert current["release_id"] == release["release_id"]
    assert current["status"] == "current"


def test_generate_catalog_refuses_when_all_sources_return_no_items(tmp_path, monkeypatch):
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)

    def fake_fetch_source(request, provider, today=None):
        return []

    monkeypatch.setattr("src.main.fetch_source", fake_fetch_source)

    with pytest.raises(ValueError):
        generate_catalog(
            config_dir="catalog-config",
            output_dir=tmp_path,
            now=now,
        )
