"""Normalised metadata with provider-specific ratings and provenance."""
import math
import re

from .identity import media_identity


_MOVIE_GENRES = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy",
    80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
    14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
    9648: "Mystery", 10749: "Romance", 878: "Science Fiction",
    10770: "TV Movie", 53: "Thriller", 10752: "War", 37: "Western",
}

_TV_GENRES = {
    10759: "Action & Adventure", 16: "Animation", 35: "Comedy",
    80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
    10762: "Kids", 9648: "Mystery", 10763: "News", 10764: "Reality",
    10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk",
    10768: "War & Politics", 37: "Western",
}


def year_number(value):
    match = re.match(r'^([0-9]{4})', str(value or ''))
    return int(match.group(1)) if match else None


def rating_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0 <= number <= 10 else None


def _normalise_genres(incoming, media_type):
    raw_genres = incoming.get("genres")
    if isinstance(raw_genres, str):
        raw_genres = [raw_genres]
    if isinstance(raw_genres, list) and raw_genres:
        names = []
        for genre in raw_genres:
            if isinstance(genre, str) and genre.strip():
                names.append(genre.strip())
            elif isinstance(genre, dict) and isinstance(genre.get("name"), str):
                if genre["name"].strip():
                    names.append(genre["name"].strip())
        if names:
            return list(dict.fromkeys(names))

    genre_map = _MOVIE_GENRES if media_type == "movie" else _TV_GENRES
    genre_ids = incoming.get("genre_ids")
    if not isinstance(genre_ids, list):
        return []

    names = []
    for genre_id in genre_ids:
        try:
            numeric_id = int(genre_id)
        except (TypeError, ValueError):
            continue
        name = genre_map.get(numeric_id)
        if name:
            names.append(name)
    return list(dict.fromkeys(names))


def merge_item(media_type, existing, incoming, provider_id):
    identity = media_identity(media_type, incoming, provider_id)
    merged = dict(existing or {})
    merged.update(id=identity['id'], type=media_type)
    ids = dict(merged.get('ids', {}))
    for key in ('imdb', 'tmdb'):
        if identity.get(key):
            ids[key] = identity[key]
    merged['ids'] = ids
    provenance = dict(merged.get('field_sources', {}))
    mapping = [
        ('name', 'title'), ('title', 'title'),
        ('poster', 'poster'), ('poster_path', 'poster'),
        ('background', 'backdrop'), ('backdrop_path', 'backdrop'),
        ('description', 'overview'), ('overview', 'description'),
        ('release_date', 'release_date'), ('first_air_date', 'release_date'),
        ('date_kind', 'date_kind'), ('date_scope', 'date_scope'),
        ('runtime', 'runtime'), ('runtime_minutes', 'runtime'),
        ('original_title', 'original_title'), ('original_name', 'original_title'),
        ('original_language', 'original_language'),
        ('popularity', 'popularity'), ('vote_count', 'vote_count'),
    ]
    for source, target in mapping:
        value = incoming.get(source)
        if value not in (None, '', []) and merged.get(target) in (None, '', []):
            merged[target] = value
            provenance[target] = provider_id

    genres = _normalise_genres(incoming, media_type)
    if genres and not merged.get('genres'):
        merged['genres'] = genres
        provenance['genres'] = provider_id

    year = year_number(
        incoming.get('releaseInfo')
        or incoming.get('year')
        or incoming.get('release_date')
        or incoming.get('first_air_date')
    )
    if merged.get('year') is None and year is not None:
        merged['year'] = year
        provenance['year'] = provider_id

    ratings = dict(merged.get('ratings', {}))
    for field, source in (('imdbRating', 'imdb'), ('tmdbRating', 'tmdb')):
        value = rating_number(incoming.get(field))
        if value is not None:
            ratings[source] = {'value': value, 'scale': 10}
    tmdb_vote = rating_number(incoming.get('vote_average'))
    if tmdb_vote is not None and 'tmdb' not in ratings:
        ratings['tmdb'] = {'value': tmdb_vote, 'scale': 10}

    merged['ratings'] = ratings
    preferred = 'imdb' if 'imdb' in ratings else ('tmdb' if 'tmdb' in ratings else None)
    merged['rating'] = ratings[preferred]['value'] if preferred else None
    merged['rating_source'] = preferred
    if preferred:
        provenance['rating'] = preferred
    merged['field_sources'] = provenance
    return merged
