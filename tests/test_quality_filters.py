from datetime import date

from src.filters import bayesian_rating, filter_snapshot_items


def _item(item_id, **overrides):
    item = {
        "id": item_id,
        "title": f"Title {item_id}",
        "poster_path": "/poster.jpg",
        "overview": "A sufficiently detailed synopsis for catalogue screening.",
        "release_date": "2026-11-22",
        "vote_average": 0,
        "vote_count": 0,
        "popularity": 1.0,
        "video": False,
        "adult": False,
    }
    item.update(overrides)
    return item


def test_bayesian_rating_does_not_trust_tiny_vote_samples():
    tiny, tiny_confidence = bayesian_rating(10, 1, prior=6, prior_votes=100)
    established, established_confidence = bayesian_rating(8, 1000, prior=6, prior_votes=100)

    assert 6.0 < tiny < 6.1
    assert tiny_confidence < 0.02
    assert established > 7.8
    assert established_confidence > 0.9


def test_new_release_gate_keeps_emerging_title_with_interest_and_metadata():
    policy = {
        "date_mode": "recent", "require_poster": True, "min_overview_length": 30,
        "min_votes_for_rating": 100, "min_bayesian_rating": 5.0,
        "min_popularity": 0.15, "max_items": 80,
    }
    candidate = _item("emerging", release_date="2026-11-20", popularity=0.8)
    accepted, excluded = filter_snapshot_items(
        [candidate], policy, request_id="new_movies", media_type="movie", today=date(2026, 11, 21)
    )
    assert [item["id"] for item in accepted] == ["emerging"]
    assert accepted[0]["_viewsync_quality"]["class"] == "emerging"
    assert not excluded


def test_new_release_gate_rejects_today_and_future_items():
    policy = {"date_mode": "recent", "min_popularity": 0.1, "min_overview_length": 10, "require_poster": True}
    items = [
        _item("yesterday", release_date="2026-11-20"),
        _item("today", release_date="2026-11-21"),
        _item("tomorrow", release_date="2026-11-22"),
    ]
    accepted, _ = filter_snapshot_items(
        items, policy, request_id="new_movies", media_type="movie", today=date(2026, 11, 21)
    )
    assert [item["id"] for item in accepted] == ["yesterday"]


def test_upcoming_emerging_title_does_not_need_vote_count():
    policy = {"date_mode": "future", "min_popularity": 0.25, "min_overview_length": 30, "require_poster": True}
    candidate = _item("upcoming", release_date="2026-12-10", popularity=1.2)
    accepted, _ = filter_snapshot_items(
        [candidate], policy, request_id="upcoming_movies", media_type="movie", today=date(2026, 11, 21)
    )
    assert len(accepted) == 1


def test_established_low_rating_and_unrated_low_interest_are_rejected():
    policy = {
        "date_mode": "none", "require_poster": True, "min_overview_length": 30,
        "min_votes_for_rating": 100, "min_bayesian_rating": 5.0,
        "min_popularity": 0.1, "max_items": 100,
    }
    rejected_rating = _item("bad", vote_average=2.5, vote_count=5000, popularity=100)
    rejected_interest = _item("unrated", popularity=0.01)
    accepted, excluded = filter_snapshot_items(
        [rejected_rating, rejected_interest], policy,
        request_id="popular_movies", media_type="movie", today=date(2026, 11, 21),
    )
    assert accepted == []
    assert excluded["low_confidence_adjusted_rating"] == 1
    assert excluded["insufficient_interest_for_unrated_title"] == 1


def test_missing_poster_and_overview_are_rejected():
    policy = {"date_mode": "none", "require_poster": True, "min_overview_length": 30}
    accepted, excluded = filter_snapshot_items(
        [_item("poster", poster_path=None), _item("overview", overview="Too short")],
        policy, request_id="popular_movies", media_type="movie", today=date(2026, 11, 21),
    )
    assert accepted == []
    assert excluded["missing_poster"] == 1
    assert excluded["insufficient_overview"] == 1


def test_same_title_year_with_distinct_tmdb_ids_are_preserved():
    policy = {"date_mode": "none", "require_poster": True, "min_overview_length": 20}
    first = _item("100", title="The Return", release_date="2026-01-01")
    second = _item("200", title="The Return", release_date="2026-01-01")
    accepted, _ = filter_snapshot_items(
        [first, second], policy, request_id="popular_movies",
        media_type="movie", today=date(2026, 11, 21),
    )
    assert {item["id"] for item in accepted} == {"100", "200"}
