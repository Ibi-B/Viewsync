import json
from pathlib import Path
import tempfile

import pytest

from src.merge_metadata import merge_item
from src.publish import publish_release
from src.validate import validate_release, ValidationError


def test_merge_item_adds_home_contract():
    incoming = {
        "title": "Example",
        "year": "2024",
        "poster": "https://example.com/poster.jpg",
        "background": "https://example.com/background.jpg",
        "overview": "Example overview",
    }
    merged = merge_item("movie", None, incoming, "tmdb")

    assert merged["identityConfidence"] == "title-year"
    assert merged["availability"] == "requires-source-selection"
    assert merged["actions"] == ["more-info", "choose-source"]
    assert merged["previewPolicy"] == "off"
    assert merged["artwork"]["poster"] == "https://example.com/poster.jpg"
    assert merged["artwork"]["landscape"] == "https://example.com/background.jpg"
    assert merged["provenance"]["providers"] == ["tmdb"]
    assert merged["provenance"]["fieldSources"]["title"] == "tmdb"


def test_publish_release_includes_home_contract():
    release = {
        "schema_version": 1,
        "release_id": "test",
        "published_at": "2026-11-09T00:00:00Z",
        "ranking_version": "1",
        "rows": [
            {
                "id": "popular_movies",
                "title": "Popular Movies",
                "media_type": "movie",
                "data_updated_at": "2026-11-09T00:00:00Z",
                "status": "ok",
                "configured_provider_count": 1,
                "contributing_provider_count": 1,
                "provenance": {"providers": ["tmdb"], "region": None, "window": "provider-default"},
                "availability": "metadata-only",
                "actions": ["more-info", "choose-source"],
                "previewPolicy": "off",
                "freshness": "fresh",
                "items": [
                    {
                        "id": "movie:tmdb:1",
                        "title": "Example",
                        "identityConfidence": "exact-id",
                        "availability": "requires-source-selection",
                        "actions": ["more-info", "choose-source"],
                        "previewPolicy": "off",
                        "artwork": {"poster": "https://example.com/poster.jpg"},
                        "provenance": {"providers": ["tmdb"], "fieldSources": {}}
                    }
                ]
            }
        ]
    }

    with tempfile.TemporaryDirectory() as tmp:
        publish_release(release, tmp)
        row_path = Path(tmp) / "v1" / "releases" / "test" / "rows" / "popular_movies.json"
        row = json.loads(row_path.read_text(encoding="utf-8"))

        assert row["availability"] == "metadata-only"
        assert row["actions"] == ["more-info", "choose-source"]
        assert row["previewPolicy"] == "off"
        assert row["freshness"] == "fresh"

        item = row["items"][0]
        assert item["identityConfidence"] == "exact-id"
        assert item["availability"] == "requires-source-selection"
        assert item["actions"] == ["more-info", "choose-source"]
        assert item["previewPolicy"] == "off"


def test_validate_rejects_bad_preview_policy():
    release = {
        "schema_version": 1,
        "release_id": "test",
        "rows": [
            {
                "id": "popular_movies",
                "title": "Popular Movies",
                "media_type": "movie",
                "data_updated_at": "2026-11-09T00:00:00Z",
                "status": "ok",
                "configured_provider_count": 1,
                "contributing_provider_count": 1,
                "previewPolicy": "invalid",
                "items": []
            }
        ]
    }

    with pytest.raises(ValidationError):
        validate_release(release)