import json
from pathlib import Path
from src import main
from src.fetch import SourceSnapshot, utc_now


def test_generation_selects_requests_and_ranks_items(tmp_path, monkeypatch):
    config = Path(__file__).resolve().parents[1] / 'catalog-config'
    def fake_fetch(request, provider):
        return SourceSnapshot(request_id=request['id'], provider_id=provider['id'],
                              list_id=request['list_id'], media_type=request['media_type'],
                              url=request['url'], fetched_at=utc_now(),
                              items=[{'imdb_id': 'tt123', 'name': 'Fixture',
                                      'release_date': '2099-01-01', 'source_rank': 1}])
    monkeypatch.setattr(main, 'fetch_source', fake_fetch)
    output = tmp_path / 'dist'
    assert main.generate(str(config), str(output), str(tmp_path / 'state')) == 0
    manifest_path = next(output.glob('v1/releases/*/manifest.json'))
    manifest = json.loads(manifest_path.read_text())
    assert len(manifest['rows']) == 4
    for entry in manifest['rows']:
        row = json.loads((output / 'v1' / entry['path']).read_text())
        assert len(row['items']) == 1
        item = row['items'][0]
        assert item['ranking']['consensus_score'] > 0
        assert item['ranking']['position'] == 1
        if entry['id'].startswith('popular_'):
            assert item['ranking']['source_count'] == 2
        assert list(manifest_path.parent.glob('items/*.json'))


def test_fresh_snapshot_overrides_previous(tmp_path, monkeypatch):
    config = Path(__file__).resolve().parents[1] / 'catalog-config'
    def snapshot(request, title):
        return SourceSnapshot(request_id=request['id'], provider_id='cinemeta',
                              list_id=request['list_id'], media_type=request['media_type'],
                              url=request['url'], fetched_at=utc_now(),
                              items=[{'imdb_id': 'tt1', 'name': title, 'source_rank': 1,
                                      'release_date': '2099-01-01'}])
    old_request = {'id': 'cinemeta_popular_movies', 'list_id': 'popular_movies',
                   'media_type': 'movie', 'url': 'https://example.invalid'}
    monkeypatch.setattr(main, 'restore_snapshots', lambda _: {old_request['id']: snapshot(old_request, 'Old')})
    monkeypatch.setattr(main, 'fetch_source', lambda request, provider: snapshot(request, 'Fresh'))
    output = tmp_path / 'dist'
    assert main.generate(str(config), str(output), str(tmp_path / 'state')) == 0
    path = next(output.glob('v1/releases/*/rows/popular_movies.json'))
    assert json.loads(path.read_text())['items'][0]['title'] == 'Fresh'
