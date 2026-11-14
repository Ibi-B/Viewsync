from src.fetch import fetch_source


def _popular_movies_request():
    return {
        "id": "popular_movies",
        "type": "movie",
        "providers": {
            "tmdb": {
                "list_id": "popular_movies",
                "media_type": "movie",
                "max_items": 10,
            }
        },
    }


def test_api_key_is_passed_to_tmdb_request(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    captured = {}
    pages = {
        1: {"page": 1, "total_pages": 2, "results": [{"id": 1, "title": "Page One"}]},
        2: {"page": 2, "total_pages": 2, "results": [{"id": 2, "title": "Page Two"}]},
    }
    calls = []

    def fake_get_json(url, params=None, headers=None, raw_responses=None):
        captured["url"] = url
        captured["params"] = params
        page = params["page"]
        calls.append(page)
        payload = pages[page]
        if raw_responses is not None:
            raw_responses.append(payload)
        return payload

    monkeypatch.setattr("src.fetch._get_json", fake_get_json)

    items = fetch_source(_popular_movies_request(), "tmdb")

    assert captured["url"].endswith("/movie/popular")
    assert captured["params"]["api_key"] == "test-key"
    assert [item["title"] for item in items] == ["Page One", "Page Two"]
    assert calls == [1, 2]


def test_missing_api_key_fails_before_request(monkeypatch):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)

    def unexpected_request(*args, **kwargs):
        raise AssertionError("TMDB request must not run without an API key")

    monkeypatch.setattr("src.fetch._get_json", unexpected_request)

    try:
        fetch_source(_popular_movies_request(), "tmdb")
    except ValueError as error:
        assert "Missing TMDB API key" in str(error)
    else:
        raise AssertionError("Expected missing TMDB API key to fail")
