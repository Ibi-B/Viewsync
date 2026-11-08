from src.fetch import SourceSnapshot, apply_authentication
from src.http_client import FetchError


def test_api_key_is_appended_from_environment(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    url = apply_authentication(
        "https://api.themoviedb.org/3/trending/movie/day",
        {"type": "api_key", "env": "TMDB_API_KEY"},
    )
    assert "api_key=test-key" in url


def test_missing_api_key_fails(monkeypatch):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    try:
        apply_authentication(
            "https://api.themoviedb.org/3/trending/movie/day",
            {"type": "api_key", "env": "TMDB_API_KEY"},
        )
    except FetchError:
        pass
    else:
        raise AssertionError("Expected FetchError")
