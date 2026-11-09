"""Catalogue adapters, external identity lookup, and source snapshots."""
import hashlib
import json
import os
import re
import urllib.parse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .http_client import FetchError, fetch_json


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


@dataclass
class SourceSnapshot:
    request_id: str
    provider_id: str
    list_id: str
    media_type: str
    url: str
    fetched_at: str
    items: list

    def to_dict(self):
        return asdict(self)


def snapshot_fingerprint(snapshot):
    return hashlib.sha256(json.dumps(snapshot.to_dict(), sort_keys=True).encode()).hexdigest()


def apply_authentication(url, auth):
    if not auth:
        return url
    if auth.get('type') != 'api_key':
        raise FetchError('Unsupported authentication type')
    key = os.environ.get(auth.get('env', ''))
    if not key:
        raise FetchError('Missing required environment variable: ' + str(auth.get('env')))
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    query['api_key'] = key
    return parsed._replace(query=urllib.parse.urlencode(query)).geturl()


def request_json(url, request):
    try:
        return fetch_json(apply_authentication(url, request.get('auth')),
                          timeout_seconds=float(request.get('timeout_seconds', 20)))
    except FetchError as error:
        message = str(error)
        key = os.environ.get((request.get('auth') or {}).get('env', ''))
        if key:
            message = message.replace(key, '[redacted]').replace(urllib.parse.quote_plus(key), '[redacted]')
        raise FetchError(message) from None


def normalise_tmdb_item(media_type, result):
    date = result.get('release_date') if media_type == 'movie' else result.get('first_air_date')
    return {
        'tmdb_id': result.get('id'), 'imdb_id': result.get('imdb_id'),
        'name': result.get('title') or result.get('name'),
        'poster': 'https://image.tmdb.org/t/p/w500' + result['poster_path'] if result.get('poster_path') else None,
        'background': 'https://image.tmdb.org/t/p/w1280' + result['backdrop_path'] if result.get('backdrop_path') else None,
        'description': result.get('overview'), 'releaseInfo': date,
        'release_date': date, 'tmdbRating': result.get('vote_average'),
        'date_kind': 'original_release' if media_type == 'movie' else 'series_premiere',
        'date_scope': 'original_not_region_specific',
    }


def future_premieres(items, today, end):
    selected = []
    for item in items:
        try:
            value = datetime.strptime(item.get('release_date', ''), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue
        if today <= value <= end:
            selected.append(item)
    return selected


def recent_releases(items, today):
    """Keep original releases in the inclusive interval [today - 30 days, today]."""
    return future_premieres(items, today - timedelta(days=30), today)


def fetch_source(request, provider):
    tmdb = provider['id'] == 'tmdb'
    upcoming = request.get('list_id', '').startswith('upcoming_')
    newly_released = request.get('list_id', '').startswith('new_')
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=30) if newly_released else today
    end = today if newly_released else today + timedelta(days=180)
    url = request['url']
    if tmdb and (upcoming or newly_released):
        movie = request['media_type'] == 'movie'
        field = 'primary_release_date' if movie else 'first_air_date'
        query = {field + '.gte': start.isoformat(), field + '.lte': end.isoformat(),
                 'sort_by': field + ('.desc' if newly_released else '.asc'), 'include_adult': 'false', 'page': 1}
        url = 'https://api.themoviedb.org/3/discover/' + ('movie' if movie else 'tv') + '?' + urllib.parse.urlencode(query)
    items = []
    total_pages = 1
    maximum = int(request.get('max_items', 100))
    for page in range(1, min(5, (maximum + 19) // 20) + 1):
        if page > total_pages:
            break
        page_url = url
        if tmdb:
            parsed = urllib.parse.urlparse(url)
            params = dict(urllib.parse.parse_qsl(parsed.query))
            params['page'] = page
            page_url = parsed._replace(query=urllib.parse.urlencode(params)).geturl()
        payload = request_json(page_url, request)
        raw = payload.get('results' if tmdb else 'metas')
        if not isinstance(raw, list):
            raise FetchError('Source did not return an item array')
        total_pages = min(int(payload.get('total_pages', 1)), 5) if tmdb else 1
        for result in raw:
            if not isinstance(result, dict):
                continue
            item = normalise_tmdb_item(request['media_type'], result) if tmdb else dict(result)
            if not tmdb and re.fullmatch(r'tt[0-9]+', str(item.get('id', ''))):
                item.setdefault('imdb_id', item['id'])
            item['source_rank'] = len(items) + 1
            items.append(item)
        if len(items) >= maximum:
            break
    items = items[:maximum]
    if upcoming:
        items = future_premieres(items, today, end)
    if newly_released:
        items = recent_releases(items, today)
    if tmdb:
        kind = 'movie' if request['media_type'] == 'movie' else 'tv'
        for item in items:
            if item.get('imdb_id') or not item.get('tmdb_id'):
                continue
            external = request_json(f"https://api.themoviedb.org/3/{kind}/{item['tmdb_id']}/external_ids", request)
            imdb = external.get('imdb_id')
            if isinstance(imdb, str) and re.fullmatch(r'tt[0-9]+', imdb):
                item['imdb_id'] = imdb
    return SourceSnapshot(request['id'], provider['id'], request['list_id'],
                          request['media_type'], request['url'], utc_now(), items)


def load_snapshot(path):
    return SourceSnapshot(**json.loads(Path(path).read_text(encoding='utf-8')))


def save_snapshot(snapshot, directory):
    path = Path(directory) / f'{snapshot.request_id}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), encoding='utf-8')
    return path
