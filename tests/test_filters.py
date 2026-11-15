"""Tests for catalogue relevance filters."""
from datetime import date

from src.filters import deduplicate_items, filter_snapshot_items, relevance_score


def test_video_and_missing_poster_are_excluded():
    config = {
        "minRelevanceScore": 20,
        "minVoteCount": 10,
        "requirePoster": True,
        "excludeVideo": True,
    }
    items = [
        {"id": "1", "title": "Video", "video": True, "poster_path": "/a.jpg", "vote_count": 100, "release_date": "2026-01-01"},
        {"id": "2", "title": "No Poster", "vote_count": 100, "release_date": "2026-01-01"},
    ]
    accepted, exclusions = filter_snapshot_items(items, config, request_id="new-movies", today=date(2026, 11, 15))
    assert not accepted
    assert [entry["reason"] for entry in exclusions] == ["video", "missingPoster"]


def test_upcoming_beyond_horizon_is_excluded():
    config = {"minRelevanceScore": 0, "maxFutureDays": 365, "requirePoster": True}
    items = [
        {"id": "1", "title": "Far Future", "poster_path": "/a.jpg", "vote_count": 100, "release_date": "2030-01-01"},
    ]
    accepted, exclusions = filter_snapshot_items(items, config, request_id="upcoming-movies", today=date(2026, 11, 15))
    assert not accepted
    assert exclusions[0]["reason"] == "futureBeyondHorizon"


def test_duplicate_title_year_keeps_stronger_record():
    config = {"minRelevanceScore": 0, "requirePoster": True}
    items = [
        {"id": "1", "title": "Same Movie", "poster_path": "/a.jpg", "vote_count": 10, "release_date": "2026-01-01"},
        {"id": "2", "title": "Same  Movie", "poster_path": "/b.jpg", "vote_count": 100, "release_date": "2026-01-01"},
    ]
    filtered, _ = filter_snapshot_items(items, config, request_id="popular", today=date(2026, 11, 15))
    accepted, exclusions = deduplicate_items(filtered)
    assert len(accepted) == 1
    assert accepted[0]["id"] == "2"
    assert exclusions[0]["reason"] == "duplicateTitleYear"


def test_adult_content_is_not_filtered():
    config = {"minRelevanceScore": 0, "requirePoster": True}
    items = [
        {"id": "1", "title": "Adult Movie", "adult": True, "poster_path": "/a.jpg", "vote_count": 100, "release_date": "2026-01-01"},
    ]
    accepted, exclusions = filter_snapshot_items(items, config, request_id="popular", today=date(2026, 11, 15))
    assert len(accepted) == 1
    assert not exclusions
