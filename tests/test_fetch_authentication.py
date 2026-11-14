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

    def fake_get_json(url, params=None, headers=None, raw_responses=None):
        captured["url"] = url
        captured["params"] = params
        return {"results": [{"id": 1, "title": "Test Movie"}]}

    monkeypatch.setattr("src.fetch._get_json", fake_get_json)

    items = fetch_source(_popular_movies_request(), "tmdb")

    assert captured["url"].endswith("/movie/popular")
    assert captured["params"]["api_key"] == "test-key"
    assert items == [{"id": 1, "title": "Test Movie"}] * 5


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
