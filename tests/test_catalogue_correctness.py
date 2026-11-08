from datetime import date
from src.fetch import fetch_source, future_premieres
from src.merge_metadata import merge_item
from src.identity import media_identity
from src import fetch


def test_future_premieres_excludes_old_missing_and_invalid_dates():
    items = [{'release_date': value} for value in ('1971-04-03', '', 'bad', '2099-02-01', '2100-01-01')]
    assert future_premieres(items, date(2099, 1, 1), date(2099, 7, 1)) == [{'release_date': '2099-02-01'}]


def test_ratings_year_and_alternate_ids_are_preserved():
    first = merge_item('movie', None, {'imdb_id': 'tt123', 'name': 'Example', 'imdbRating': '8.1', 'releaseInfo': '2026–2027'}, 'cinemeta')
    result = merge_item('movie', first, {'imdb_id': 'tt123', 'tmdb_id': 42, 'tmdbRating': 7.2, 'release_date': '2026-12-01'}, 'tmdb')
    assert result['ids'] == {'imdb': 'tt123', 'tmdb': '42'}
    assert result['year'] == 2026
    assert result['rating'] == 8.1
    assert result['rating_source'] == 'imdb'
    assert result['ratings']['tmdb']['value'] == 7.2


def test_tmdb_external_ids_produce_shared_identity(monkeypatch):
    def fake(url, request):
        if '/external_ids' in url:
            return {'imdb_id': 'tt123'}
        return {'results': [{'id': 42, 'title': 'Example', 'release_date': '2026-12-01'}], 'total_pages': 1}
    monkeypatch.setattr(fetch, 'request_json', fake)
    request = {'id': 'tmdb_movies', 'list_id': 'popular_movies', 'media_type': 'movie',
               'url': 'https://example.invalid/list', 'max_items': 20}
    result = fetch_source(request, {'id': 'tmdb'})
    assert media_identity('movie', result.items[0])['id'] == media_identity('movie', {'imdb_id': 'tt123'})['id']


def test_upcoming_series_uses_discover_premiere_window(monkeypatch):
    calls = []
    def fake(url, request):
        calls.append(url)
        return {'results': [], 'total_pages': 1}
    monkeypatch.setattr(fetch, 'request_json', fake)
    fetch_source({'id': 'upcoming', 'list_id': 'upcoming_series', 'media_type': 'series',
                  'url': 'https://api.themoviedb.org/3/tv/on_the_air', 'max_items': 20}, {'id': 'tmdb'})
    assert '/discover/tv?' in calls[0]
    assert 'first_air_date.gte=' in calls[0]
    assert 'first_air_date.lte=' in calls[0]
