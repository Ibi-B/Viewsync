import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from src import fetch, main
from src.fetch import SourceSnapshot, recent_releases


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2099, 1, 31, 12, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


@pytest.mark.parametrize('offset,included', [(-31, False), (-30, True), (-1, True), (0, True), (1, False)])
def test_recent_release_boundaries(offset, included):
    today = date(2099, 1, 31)
    item = {'release_date': (today + timedelta(days=offset)).isoformat()}
    assert bool(recent_releases([item], today)) is included


@pytest.mark.parametrize('value', ['', None, 'bad', '2099-02-30'])
def test_recent_releases_reject_unknown_and_invalid_dates(value):
    assert recent_releases([{'release_date': value}], date(2099, 1, 31)) == []


@pytest.mark.parametrize('media,endpoint,field', [('movie', 'movie', 'primary_release_date'), ('series', 'tv', 'first_air_date')])
def test_new_discovery_query_and_local_filter(monkeypatch, media, endpoint, field):
    monkeypatch.setattr(fetch, 'datetime', FixedDatetime)
    calls = []
    def fake(url, request):
        calls.append(url)
        if '/external_ids' in url:
            return {'imdb_id': 'tt1'}
        date_key = 'release_date' if media == 'movie' else 'first_air_date'
        return {'total_pages': 1, 'results': [
            {'id': index, 'title': 'Fixture', date_key: value}
            for index, value in enumerate(['2098-12-31', '2099-01-01', '2099-01-31', '2099-02-01', '', 'bad'], 1)
        ]}
    monkeypatch.setattr(fetch, 'request_json', fake)
    result = fetch.fetch_source({'id': 'new', 'list_id': 'new_movies' if media == 'movie' else 'new_series', 'media_type': media, 'url': 'https://example.invalid', 'max_items': 20}, {'id': 'tmdb'})
    parsed = urlparse(calls[0])
    params = parse_qs(parsed.query)
    assert parsed.path == '/3/discover/' + endpoint
    assert params[field + '.gte'] == ['2099-01-01']
    assert params[field + '.lte'] == ['2099-01-31']
    assert params['sort_by'] == [field + '.desc']
    assert [item['release_date'] for item in result.items] == ['2099-01-01', '2099-01-31']
    assert all(item['imdb_id'] == 'tt1' for item in result.items)
    assert len(calls) == 3


@pytest.mark.parametrize('mode,expected', [('upcoming_movies', 'primary_release_date.asc'), ('popular_movies', None)])
def test_existing_query_modes_unchanged(monkeypatch, mode, expected):
    calls = []
    def fake(url, request):
        calls.append(url)
        return {'total_pages': 1, 'results': []}
    monkeypatch.setattr(fetch, 'request_json', fake)
    fetch.fetch_source({'id': mode, 'list_id': mode, 'media_type': 'movie', 'url': 'https://api.themoviedb.org/3/trending/movie/day'}, {'id': 'tmdb'})
    parsed = urlparse(calls[0])
    if expected:
        assert parse_qs(parsed.query)['sort_by'] == [expected]
    else:
        assert parsed.path == '/3/trending/movie/day'
        assert 'sort_by' not in parse_qs(parsed.query)


@pytest.mark.parametrize('retained,empty', [(False, False), (True, False), (False, True)])
def test_published_new_rows_order_filter_and_empty_snapshot(tmp_path, monkeypatch, retained, empty):
    monkeypatch.setattr(main, 'datetime', FixedDatetime)
    now = FixedDatetime.now(timezone.utc).isoformat()
    previous = {}
    def fake(request, provider):
        is_new = request['list_id'].startswith('new_')
        items = [] if is_new and empty else [
            {'imdb_id': 'tt' + str(index), 'name': 'Fixture', 'source_rank': index, 'release_date': value}
            for index, value in enumerate(['2099-01-10', '2099-01-31', '2098-12-01', '2099-02-01', '2099-01-31'], 1)
        ]
        value = SourceSnapshot(request['id'], provider['id'], request['list_id'], request['media_type'], request['url'], now, items)
        if retained and is_new:
            from src.http_client import FetchError
            raise FetchError('offline')
        return value
    config = Path(__file__).resolve().parents[1] / 'catalog-config'
    source_config = json.loads((config / 'sources.json').read_text())
    if retained:
        for provider in source_config['providers']:
            for request in provider['requests']:
                if request['list_id'].startswith('new_'):
                    previous[request['id']] = SourceSnapshot(request['id'], provider['id'], request['list_id'], request['media_type'], request['url'], now, [
                        {'imdb_id': 'tt' + str(index), 'name': 'Fixture', 'source_rank': index, 'release_date': value}
                        for index, value in enumerate(['2099-01-10', '2099-01-31', '2098-12-01', '2099-02-01', '2099-01-31'], 1)
                    ])
    monkeypatch.setattr(main, 'fetch_source', fake)
    monkeypatch.setattr(main, 'restore_snapshots', lambda _: previous)
    output = tmp_path / 'dist'
    assert main.generate(config, output, tmp_path / 'state') == 0
    manifest = json.loads((output / 'v1/manifest.json').read_text())
    assert {row['id'] for row in manifest['rows']} == {'new_movies', 'new_series', 'popular_movies', 'popular_series', 'upcoming_movies', 'upcoming_series'}
    for entry in manifest['rows']:
        row = json.loads((output / 'v1' / entry['path']).read_text())
        if row['id'].startswith('new_'):
            assert [item['release_date'] for item in row['items']] == ([] if empty else ['2099-01-31', '2099-01-31', '2099-01-10'])
            assert [item['ranking']['position'] for item in row['items']] == list(range(1, len(row['items']) + 1))
            if not empty:
                assert row['items'][0]['id'].endswith('tt2')
                assert row['items'][1]['id'].endswith('tt5')
            if retained:
                assert row['status'] == 'retained'
