from src.identity import media_identity, same_media


def test_movie_identity_prefers_imdb():
    identity = media_identity("movie", {"imdb_id": "tt123", "name": "Example"})
    assert identity["id"] == "movie:imdb:tt123"


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
