from datetime import date

from src.fetch import date_window, fetch_source


def _request(request_id, media_type, mode, max_items=10):
    return {
        "id": request_id,
        "providers": {
            "tmdb": {
                "list_id": request_id,
                "media_type": media_type,
                "max_items": max_items,
                "date_mode": mode,
            }
        },
    }


def test_recent_window_ends_yesterday_and_upcoming_starts_today():
    today = date(2026, 11, 21)
    _, recent_start, recent_end, recent_order = date_window("recent", today, "movie")
    _, upcoming_start, upcoming_end, upcoming_order = date_window("future", today, "movie")

    assert recent_start == date(2026, 10, 22)
    assert recent_end == date(2026, 11, 20)
    assert upcoming_start == date(2026, 11, 21)
    assert upcoming_end == date(2027, 5, 20)
    assert recent_end < upcoming_start
    assert recent_order == "popularity.desc"
    assert upcoming_order == "popularity.desc"


def test_series_uses_first_air_date_window():
    today = date(2026, 11, 21)
    field, start, end, _ = date_window("recent", today, "series")
    assert field == "first_air_date"
    assert start == date(2026, 10, 22)
    assert end == date(2026, 11, 20)


def test_recent_upcoming_fetch_uses_wider_candidate_pool(monkeypatch):
    calls = []
    monkeypatch.setenv("TMDB_API_KEY", "test-only-key")

    def fake_get_json(url, params=None, headers=None, raw_responses=None):
        calls.append(dict(params or {}))
        return {
            "page": params["page"],
            "total_pages": 40,
            "results": [{"id": params["page"], "title": f"Item {params['page']}"}],
        }

    monkeypatch.setattr("src.fetch._get_json", fake_get_json)
    items = fetch_source(
        _request("upcoming_movies", "movie", "future", 500),
        "tmdb",
        today=date(2026, 11, 21),
    )

    # Candidate retrieval is bounded at 25 pages; the final quality policy
    # narrows that pool to the configured published row size.
    assert len(calls) == 25
    assert len(items) == 25


def test_discovery_fetch_uses_popularity_order_and_bounded_pages(monkeypatch):
    calls = []
    monkeypatch.setenv("TMDB_API_KEY", "test-only-key")

    def fake_get_json(url, params=None, headers=None, raw_responses=None):
        calls.append((url, dict(params or {})))
        return {"page": params["page"], "total_pages": 9, "results": [{"id": params["page"], "title": f"Item {params['page']}"}]}

    monkeypatch.setattr("src.fetch._get_json", fake_get_json)
    items = fetch_source(_request("upcoming_movies", "movie", "future", 3), "tmdb", today=date(2026, 11, 21))

    assert len(items) == 3
    assert [entry[1]["page"] for entry in calls] == [1, 2, 3]
    assert all(entry[1]["sort_by"] == "popularity.desc" for entry in calls)
    assert all(entry[1]["primary_release_date.gte"] == "2026-11-21" for entry in calls)
