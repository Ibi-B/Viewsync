from datetime import datetime, timezone

from src.fetch import SourceSnapshot
from src.state import retention_status, snapshot_age_hours


def make_snapshot(fetched_at):
    return SourceSnapshot(
        request_id="test",
        provider_id="provider",
        list_id="list",
        media_type="movie",
        url="https://example.invalid",
        fetched_at=fetched_at,
        items=[],
    )


def test_fresh_snapshot():
    snapshot = make_snapshot("2026-01-01T00:00:00Z")
    now = datetime(2026, 1, 1, 6, tzinfo=timezone.utc)
    assert retention_status(snapshot_age_hours(snapshot, now), {}) == "fresh"


def test_retained_snapshot():
    snapshot = make_snapshot("2026-01-01T00:00:00Z")
    now = datetime(2026, 1, 2, 6, tzinfo=timezone.utc)
    assert retention_status(snapshot_age_hours(snapshot, now), {}) == "retained_full"


def test_expired_snapshot():
    snapshot = make_snapshot("2026-01-01T00:00:00Z")
    now = datetime(2026, 1, 5, 6, tzinfo=timezone.utc)
    assert retention_status(snapshot_age_hours(snapshot, now), {}) == "expired"
