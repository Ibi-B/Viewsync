from src.fetch import SourceSnapshot, apply_authentication


def test_apply_authentication_prefers_bearer_token(monkeypatch):
    monkeypatch.setenv("TMDB_ACCESS_TOKEN", "test-token")

    request = {
        "id": "popular_movies",
        "providers": {
            "tmdb": {
                "list_id": "popular_movies",
                "media_type": "movie",
            }
        },
    }

    auth = apply_authentication(request, "tmdb")

    assert auth["headers"] == {"Authorization": "Bearer test-token"}
    assert auth["params"] == {}


def test_apply_authentication_falls_back_to_api_key(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    request = {
        "id": "popular_movies",
        "providers": {
            "tmdb": {
                "list_id": "popular_movies",
                "media_type": "movie",
            }
        },
    }

    auth = apply_authentication(request, "tmdb")

    assert auth["headers"] == {}
    assert auth["params"] == {"api_key": "test-key"}


def test_source_snapshot_holds_required_fields():
    snapshot = SourceSnapshot(
        request_id="popular_movies",
        provider_id="tmdb",
        list_id="popular_movies",
        media_type="movie",
        items=[],
    )

    assert snapshot.request_id == "popular_movies"
    assert snapshot.provider_id == "tmdb"