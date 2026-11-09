from datetime import datetime, timezone

import pytest

from src.fetch import SourceSnapshot
from src.manifest import build_release
from src.validate import ValidationError, validate_release


def _snapshot(provider_id, items):
    return SourceSnapshot(
        request_id="popular_movies",
        provider_id=provider_id,
        list_id="popular_movies",
        media_type="movie",
        fetched_at="2026-11-09T00:00:00+00:00",
        items=items,
    )


def _valid_release():
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    snapshots = [
        _snapshot(
            "provider-a",
            [
                {
                    "imdb_id": "tt0111161",
                    "name": "The Shawshank Redemption",
                    "year": "1994",
                    "poster": "https://example.com/poster.jpg",
                    "description": "A prison drama.",
                }
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
    return build_release(rows, snapshots, now)


def test_valid_release_passes_contract_validation():
    release = _valid_release()
    validate_release(release)

    assert release["schema_version"] == 2
    assert release["rows"][0]["items"][0]["media_kind"] == "movie"
    assert release["rows"][0]["items"][0]["source_attribution"][0]["freshness"] == "fresh"


def test_release_rejects_unsupported_schema_version():
    release = _valid_release()
    release["schema_version"] = 1

    with pytest.raises(ValidationError):
        validate_release(release)


def test_release_rejects_invalid_media_kind():
    release = _valid_release()
    release["rows"][0]["items"][0]["media_kind"] = "unknown"

    with pytest.raises(ValidationError):
        validate_release(release)


def test_release_rejects_invalid_image_url():
    release = _valid_release()
    release["rows"][0]["items"][0]["images"]["poster"] = "not-a-url"

    with pytest.raises(ValidationError):
        validate_release(release)


def test_release_rejects_missing_source_attribution():
    release = _valid_release()
    release["rows"][0]["items"][0]["source_attribution"] = []

    with pytest.raises(ValidationError):
        validate_release(release)


def test_release_rejects_invalid_freshness():
    release = _valid_release()
    release["rows"][0]["items"][0]["source_attribution"][0]["freshness"] = "stale"

    with pytest.raises(ValidationError):
        validate_release(release)
