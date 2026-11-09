"""Static publication. All catalogue paths resolve against the v1 root."""
import hashlib
import json
import re
from pathlib import Path
from .validate import validate_release


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(path)
    return path


def safe_component(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError(f'Unsafe publication identifier: {value!r}')
    return value


def _detail_filename(media_id: str) -> str:
    digest = hashlib.sha256(media_id.encode('utf-8')).hexdigest()[:24]
    return f'{digest}.json'


def publish_release(release, output_dir):
    validate_release(release)
    root = Path(output_dir) / 'v1'
    release_id = safe_component(release['release_id'])
    directory = root / 'releases' / release_id

    manifest = {
        key: release[key]
        for key in (
            'schema_version',
            'release_id',
            'generated_at',
            'ranking_version',
            'catalog_freshness',
        )
    }
    manifest.update(
        path_base='v1-root',
        manifest_path=f'releases/{release_id}/manifest.json',
        rows=[],
    )

    targets = []

    for row in release['rows']:
        row_id = safe_component(row['id'])
        path = directory / 'rows' / f'{row_id}.json'
        entry = {
            key: row[key]
            for key in (
                'id',
                'title',
                'media_kind',
                'data_updated_at',
                'status',
                'configured_provider_count',
                'contributing_provider_count',
            )
        }
        entry['path'] = path.relative_to(root).as_posix()
        manifest['rows'].append(entry)

        items = []
        for source in row['items']:
            item = dict(source)
            filename = _detail_filename(item['id'])
            detail_path = directory / 'items' / filename
            item['details_path'] = detail_path.relative_to(root).as_posix()

            details = {
                key: value
                for key, value in source.items()
                if key not in ('ranking', 'details_path')
            }
            write_json(detail_path, details)
            targets.append(detail_path)
            items.append(item)

        payload = {
            key: row[key]
            for key in (
                'id',
                'title',
                'media_type',
                'media_kind',
                'data_updated_at',
                'status',
            )
        }
        payload.update(
            schema_version=2,
            release_id=release_id,
            path_base='v1-root',
            items=items,
        )
        write_json(path, payload)
        targets.append(path)

    for target in targets:
        json.loads(target.read_text(encoding='utf-8'))

    write_json(directory / 'manifest.json', manifest)
    return write_json(root / 'manifest.json', manifest)
