"""Normalised metadata with provider-specific ratings and provenance."""
import re
import math
from .identity import media_identity


def year_number(value):
    match = re.match(r'^([0-9]{4})', str(value or ''))
    return int(match.group(1)) if match else None


def rating_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0 <= number <= 10 else None


def merge_item(media_type, existing, incoming, provider_id):
    identity = media_identity(media_type, incoming)
    merged = dict(existing or {})
    merged.update(id=identity['id'], type=media_type)
    ids = dict(merged.get('ids', {}))
    for key in ('imdb', 'tmdb'):
        if identity.get(key):
            ids[key] = identity[key]
    merged['ids'] = ids
    provenance = dict(merged.get('field_sources', {}))
    mapping = [('name', 'title'), ('title', 'title'), ('poster', 'poster'),
               ('background', 'backdrop'), ('description', 'overview'),
               ('release_date', 'release_date'), ('date_kind', 'date_kind'),
               ('date_scope', 'date_scope')]
    for source, target in mapping:
        value = incoming.get(source)
        if value not in (None, '', []) and merged.get(target) in (None, '', []):
            merged[target] = value
            provenance[target] = provider_id
    year = year_number(incoming.get('releaseInfo') or incoming.get('year') or incoming.get('release_date'))
    if merged.get('year') is None and year is not None:
        merged['year'] = year
        provenance['year'] = provider_id
    ratings = dict(merged.get('ratings', {}))
    for field, source in (('imdbRating', 'imdb'), ('tmdbRating', 'tmdb')):
        value = rating_number(incoming.get(field))
        if value is not None:
            ratings[source] = {'value': value, 'scale': 10}
    merged['ratings'] = ratings
    preferred = 'imdb' if 'imdb' in ratings else ('tmdb' if 'tmdb' in ratings else None)
    merged['rating'] = ratings[preferred]['value'] if preferred else None
    merged['rating_source'] = preferred
    if preferred:
        provenance['rating'] = preferred
    merged['field_sources'] = provenance
    return merged
