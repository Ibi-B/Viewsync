from src.identity import media_identity, same_media


def test_tmdb_id_remains_canonical_when_imdb_alias_is_available():
    identity = media_identity(
        "movie",
        {"id": 123, "tmdb_id": "123", "imdb_id": "tt123", "name": "Example"},
        provider_id="tmdb",
    )
    assert identity["id"] == "movie:tmdb:123"
    assert identity["imdb"] == "tt123"
    assert identity["tmdb"] == "123"


def test_series_identity_uses_tmdb_when_imdb_missing():
    identity = media_identity("series", {"tmdb_id": "456", "name": "Example"})
    assert identity["id"] == "series:tmdb:456"


def test_same_media_matches_imdb():
    left = media_identity("movie", {"imdb_id": "tt123"})
    right = media_identity("movie", {"imdb": "tt123", "name": "Other title"})
    assert same_media(left, right)


def test_movie_and_series_are_not_merged():
    left = media_identity("movie", {"imdb_id": "tt123"})
    right = media_identity("series", {"imdb_id": "tt123"})
    assert not same_media(left, right)


def test_tmdb_canonical_id_is_stable_when_external_ids_are_missing_or_added():
    before = media_identity(
        "movie",
        {"id": 123, "name": "Example"},
        provider_id="tmdb",
    )
    after = media_identity(
        "movie",
        {"id": 123, "tmdb_id": "123", "imdb_id": "tt123", "name": "Example"},
        provider_id="tmdb",
    )
    assert before["id"] == after["id"] == "movie:tmdb:123"
