from src.identity import media_identity, resolve_identity, same_media


def test_imdb_only_and_tmdb_only_same_title_year_match():
    imdb_only = media_identity(
        "movie",
        {"imdb_id": "tt0111161", "title": "The Shawshank Redemption", "year": "1994"},
    )
    tmdb_only = media_identity(
        "movie",
        {"tmdb_id": "278", "name": "The Shawshank Redemption", "release_date": "1994-09-23"},
    )

    assert same_media(imdb_only, tmdb_only) is True


def test_imdb_only_and_tmdb_only_different_years_do_not_match():
    imdb_only = media_identity(
        "movie",
        {"imdb_id": "tt0111161", "title": "The Shawshank Redemption", "year": "1994"},
    )
    tmdb_only = media_identity(
        "movie",
        {"tmdb_id": "999", "title": "The Shawshank Redemption", "year": "2004"},
    )

    assert same_media(imdb_only, tmdb_only) is False


def test_cross_match_requires_matching_media_type():
    movie = media_identity(
        "movie",
        {"imdb_id": "tt0111161", "title": "The Shawshank Redemption", "year": "1994"},
    )
    series = media_identity(
        "series",
        {"tmdb_id": "278", "name": "The Shawshank Redemption", "year": "1994"},
    )

    assert same_media(movie, series) is False


def test_resolver_reuses_existing_cross_matched_identity():
    identities = {}
    first = resolve_identity(
        "movie",
        {"imdb_id": "tt0111161", "title": "The Shawshank Redemption", "year": "1994"},
        identities,
    )
    second = resolve_identity(
        "movie",
        {"tmdb_id": "278", "name": "The Shawshank Redemption", "release_date": "1994-09-23"},
        identities,
    )

    assert first == second
    assert len(identities) == 1


def test_resolver_does_not_merge_ambiguous_title_without_year():
    identities = {}
    first = resolve_identity(
        "movie",
        {"imdb_id": "tt0111161", "title": "The Shawshank Redemption"},
        identities,
    )
    second = resolve_identity(
        "movie",
        {"tmdb_id": "278", "name": "The Shawshank Redemption"},
        identities,
    )

    assert first != second
    assert len(identities) == 2


def test_title_normalisation_ignores_articles_and_punctuation():
    assert same_media(
        media_identity("movie", {"imdb_id": "tt1", "title": "The Matrix", "year": "1999"}),
        media_identity("movie", {"tmdb_id": "603", "name": "Matrix!", "year": "1999"}),
    )
