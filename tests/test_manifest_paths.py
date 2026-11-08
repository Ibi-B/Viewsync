import json
from urllib.parse import urljoin
import pytest
from src.publish import publish_release
from tests.test_publish import make_release


def test_stable_manifest_and_all_links(tmp_path):
    path = publish_release(make_release(), tmp_path)
    assert path == tmp_path / 'v1/manifest.json'
    manifest = json.loads(path.read_text())
    root = tmp_path / 'v1'
    assert json.loads((root / manifest['manifest_path']).read_text()) == manifest
    assert manifest['path_base'] == 'v1-root'
    for entry in manifest['rows']:
        assert '\\' not in entry['path']
        assert not entry['path'].startswith('/')
        base = 'https://example.test/Viewsync/v1/'
        assert urljoin(base, entry['path']).startswith(base + 'releases/')
        row = json.loads((root / entry['path']).read_text())
        assert row['release_id'] == manifest['release_id']
        for item in row['items']:
            detail = json.loads((root / item['details_path']).read_text())
            assert detail['id'] == item['id']


def test_release_dates_survive_detail_publication(tmp_path):
    release = make_release()
    release['rows'][0]['items'][0]['release_date'] = '2099-01-01'
    path = publish_release(release, tmp_path)
    root = path.parent
    manifest = json.loads(path.read_text())
    row = json.loads((root / manifest['rows'][0]['path']).read_text())
    detail = json.loads((root / row['items'][0]['details_path']).read_text())
    assert detail['release_date'] == '2099-01-01'


def test_rejects_unsafe_release_path(tmp_path):
    release = make_release()
    release['release_id'] = '../escape'
    with pytest.raises(ValueError):
        publish_release(release, tmp_path)
    assert not (tmp_path / 'v1/manifest.json').exists()
