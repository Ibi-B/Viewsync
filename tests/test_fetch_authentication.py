from datetime import date

import src.fetch as fetch


def _request():
    return {
        "id": "popular_movies",
        "providers": {
            "tmdb": {
                "list_id": "popular_movies",
                "media_type": "movie",
                "max_items": 1,
            }
        },
    }


def test_tmdb_api_key_is_passed_to_provider_request(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    captured = {}

    def fake_get_json(url, params=None):
        captured["url"] = url
        captured["params"] = params or {}
        return {"results": [{"id": 1, "title": "Fixture", "release_date": "2026-01-01"}]}

    monkeypatch.setattr(fetch, "_get_json", fake_get_json)
    items = fetch.fetch_source(_request(), "tmdb", date(2026, 11, 10))

    assert len(items) == 1
    assert captured["params"]["api_key"] == "test-key"


def test_missing_tmdb_api_key_fails_before_network(monkeypatch):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("network must not be called without an API key")

    monkeypatch.setattr(fetch, "_get_json", fail_if_called)
    try:
        fetch.fetch_source(_request(), "tmdb", date(2026, 11, 10))
    except ValueError as error:
        assert "Missing TMDB API key" in str(error)
    else:
        raise AssertionError("Expected ValueError for missing TMDB API key")
