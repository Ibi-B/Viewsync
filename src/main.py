"""Viewsync catalogue generation entry point."""
import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config
from .fetch import fetch_source, utc_now
from .http_client import FetchError
from .identity import media_identity
from .merge_metadata import merge_item
from .publish import publish_release
from .rank import build_ranking, order_items
from .state import persist_snapshots, restore_snapshots, retention_status, snapshot_age_hours
from .validate import has_usable_items, validate_snapshot


def generate(config_dir, output_dir, state_dir):
    config = load_config(config_dir)
    previous = restore_snapshots(state_dir)
    fresh = {}
    requests = {}
    for provider in config['sources'].get('providers', []):
        if not provider.get('enabled'):
            continue
        for request in provider.get('requests', []):
            requests[request['id']] = provider['id']
            try:
                snapshot = fetch_source(request, provider)
                validate_snapshot(snapshot)
                if not has_usable_items(snapshot):
                    raise FetchError('Source returned no usable items')
                fresh[snapshot.request_id] = snapshot
                print(f"Fetched {request['id']}: {len(snapshot.items)} items", flush=True)
            except (FetchError, ValueError) as error:
                print(f"Source failure: {request['id']}: {error}", file=sys.stderr, flush=True)

    combined = dict(previous)
    combined.update(fresh)
    policy = config['ranking'].get('freshness', {})
    now = datetime.now(timezone.utc)
    eligible = {key: snapshot for key, snapshot in combined.items()
                if key in requests and retention_status(snapshot_age_hours(snapshot, now), policy) != 'expired'}
    rows = []
    for row in config['rows'].get('rows', []):
        snapshots = [eligible[key] for key in row['source_lists']
                     if key in eligible and eligible[key].media_type == row['media_type']]
        if not snapshots:
            print(f"No eligible snapshots for row {row['id']}", file=sys.stderr)
            continue
        merged = {}
        for snapshot in sorted(snapshots, key=lambda s: s.request_id):
            for meta in snapshot.items:
                media_id = media_identity(snapshot.media_type, meta)['id']
                meta['_viewsync_id'] = media_id
                item = merge_item(snapshot.media_type, merged.get(media_id), meta, snapshot.provider_id)
                item['_viewsync_id'] = media_id
                merged[media_id] = item
        rankings = build_ranking(snapshots, k=int(config['ranking'].get('k', 60)),
                                 provider_weights=config['ranking'].get('provider_weights', {}))
        ordered = order_items(list(merged.values()), rankings)
        if row.get('date_field'):
            field = row['date_field']
            ordered = sorted((item for item in ordered if item.get(field)),
                             key=lambda item: (item[field], item['id']))
        items = []
        for position, item in enumerate(ordered[:int(row.get('max_items', 100))], 1):
            result = {key: value for key, value in item.items() if not key.startswith('_')}
            result['ranking'] = dict(rankings[item['id']], position=position)
            items.append(result)
        configured = {requests[key] for key in row['source_lists']}
        contributing = {s.provider_id for s in snapshots}
        retained = any(s.request_id not in fresh for s in snapshots)
        status = 'reduced_coverage' if configured != contributing else ('retained' if retained else 'fresh')
        rows.append(dict(id=row['id'], title=row['title'], media_type=row['media_type'],
                         data_updated_at=max(s.fetched_at for s in snapshots), status=status,
                         configured_provider_count=len(configured),
                         contributing_provider_count=len(contributing), items=items))
    if not rows:
        print('No rows could be generated.', file=sys.stderr)
        return 1
    release_id = uuid.uuid4().hex
    release = dict(schema_version=1, release_id=release_id, published_at=utc_now(),
                   ranking_version='rrf-v1', rows=rows)
    manifest = publish_release(release, output_dir)
    persist_snapshots(list(fresh.values()), state_dir)
    marker = Path(state_dir) / 'last-good-release' / 'release.json'
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({'release_id': release_id}), encoding='utf-8')
    print(f'Published release {release_id}: {manifest}')
    return 0


def main():
    parser = argparse.ArgumentParser(description='Generate the Viewsync catalogue')
    parser.add_argument('--config', default='catalog-config')
    parser.add_argument('--output', default='dist')
    parser.add_argument('--state', default='state')
    args = parser.parse_args()
    return generate(args.config, args.output, args.state)


if __name__ == '__main__':
    raise SystemExit(main())
