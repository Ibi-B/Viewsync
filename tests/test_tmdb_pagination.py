from datetime import date

from src.fetch import _collect_tmdb_pages, fetch_source


def test_tmdb_pagination_stops_immediately_on_empty_page(monkeypatch):
    calls = []

    def fake_get_json(url, params=None, headers=None, raw_responses=None):
        calls.append(params["page"])
        if params["page"] == 1:
            return {"page": 1, "total_pages": 5, "results": [{"id": 1}]}
        return {"page": 2, "total_pages": 5, "results": []}

    monkeypatch.setattr("src.fetch._get_json", fake_get_json)

    items = _collect_tmdb_pages("https://example.invalid/list", {}, 20)

    assert items == [{"id": 1}]
    assert calls == [1, 2]


def test_tmdb_date_window_uses_bounded_pagination_and_item_limit(monkeypatch):
    request = {
        "id": "new_movies",
        "type": "movie",
        "providers": {
            "tmdb": {
                "list_id": "new_movies",
                "media_type": "movie",
                "max_items": 3,
                "date_mode": "recent",
            }
        },
    }
    pages = {
        1: {"page": 1, "total_pages": 4, "results": [{"id": 1}, {"id": 2}]},
        2: {"page": 2, "total_pages": 4, "results": [{"id": 3}, {"id": 4}]},
    }
    calls = []

    monkeypatch.setenv("TMDB_API_KEY", "test-only-key")

    def fake_get_json(url, params=None, headers=None, raw_responses=None):
        page = params["page"]
        calls.append(page)
        return pages[page]

    monkeypatch.setattr("src.fetch._get_json", fake_get_json)

    items = fetch_source(request, "tmdb", today=date(2026, 11, 15))

    assert [item["id"] for item in items] == [1, 2, 3]
    assert calls == [1, 2]


def test_tmdb_static_list_keeps_five_page_safety_cap(monkeypatch):
    calls = []

    def fake_get_json(url, params=None, headers=None, raw_responses=None):
        page = params["page"]
        calls.append(page)
        return {"page": page, "total_pages": 9, "results": [{"id": page}]}

    monkeypatch.setattr("src.fetch._get_json", fake_get_json)

    items = _collect_tmdb_pages(
        "https://example.invalid/list",
        {},
        max_items=100,
    )

    assert [item["id"] for item in items] == [1, 2, 3, 4, 5]
    assert calls == [1, 2, 3, 4, 5]


def test_tmdb_pagination_does_not_fetch_when_item_limit_is_zero(monkeypatch):
    def unexpected_request(*args, **kwargs):
        raise AssertionError("No page should be fetched for a zero item limit")

    monkeypatch.setattr("src.fetch._get_json", unexpected_request)

    assert _collect_tmdb_pages("https://example.invalid/list", {}, 0) == []
