import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

TMDB_BASE = "https://api.themoviedb.org/3"
IMDB_BASE = "https://v3.sg.media-imdb.com/suggestion"
TRAKT_BASE = "https://api.trakt.tv"
STREMIO_BASE = "https://v3-cinemeta.strem.io"


@dataclass
class SourceSnapshot:
    """A persisted result of one provider request at one point in time."""

    request_id: str
    provider_id: str
    list_id: str
    media_type: str
    fetched_at: str
    items: List[Dict[str, Any]]


def _get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def _extract_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("results", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _normalise_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _title_candidates(item: Dict[str, Any]) -> List[str]:
    values = [
        item.get("title"),
        item.get("name"),
        item.get("original_title"),
        item.get("original_name"),
    ]
    return [str(value) for value in values if value]


def _year_candidates(item: Dict[str, Any]) -> List[str]:
    values = [
        item.get("year"),
        item.get("release_date"),
        item.get("first_air_date"),
    ]
    years = []
    for value in values:
        if not value:
            continue
        text = str(value)
        match = re.search(r"\d{4}", text)
        if match:
            years.append(match.group(0))
    return years


def _matches_request(
    item: Dict[str, Any],
    title: str,
    year: Optional[int],
    media_type: str,
) -> bool:
    item_media_type = _normalise_text(item.get("media_type") or item.get("type"))
    if media_type and item_media_type and item_media_type != media_type:
        return False

    item_titles = [_normalise_text(value) for value in _title_candidates(item)]
    if not item_titles:
        return False
    if _normalise_text(title) not in item_titles:
        return False

    if year:
        item_years = [
            int(value)
            for value in _year_candidates(item)
            if str(value).isdigit()
        ]
        if item_years and year not in item_years:
            return False

    return True


def _imdb_suggestions(
    title: str,
    media_type: str,
    year: Optional[int],
) -> List[Dict[str, Any]]:
    media_path = "movie" if media_type == "movie" else "tv"
    url = f"{IMDB_BASE}/{media_path}/{title}.json"
    payload = _get_json(url)
    items = _extract_items(payload)
    return [
        item
        for item in items
        if _matches_request(item, title, year, media_type)
    ]


def _tmdb_search(
    title: str,
    media_type: str,
    year: Optional[int],
    api_key: str,
) -> List[Dict[str, Any]]:
    endpoint = "movie" if media_type == "movie" else "tv"
    params: Dict[str, Any] = {
        "query": title,
        "include_adult": "false",
    }

    if year:
        if media_type == "movie":
            params["year"] = year
        else:
            params["first_air_date_year"] = year

    payload = _get_json(
        f"{TMDB_BASE}/search/{endpoint}",
        params={"api_key": api_key, **params},
    )
    return _extract_items(payload)


def _tmdb_list(
    list_id: str,
    media_type: str,
    api_key: str,
    max_items: int = 100,
) -> List[Dict[str, Any]]:
    endpoints = {
        "popular_movies": "movie/popular",
        "popular_series": "tv/popular",
        "new_movies": "movie/now_playing",
        "new_series": "tv/airing_today",
        "upcoming_movies": "movie/upcoming",
        "upcoming_series": "tv/on_the_air",
    }

    endpoint = endpoints.get(list_id)
    if not endpoint:
        return []

    items: List[Dict[str, Any]] = []
    page = 1

    while len(items) < max_items and page <= 5:
        payload = _get_json(
            f"{TMDB_BASE}/{endpoint}",
            params={"api_key": api_key, "page": page},
        )
        page_items = _extract_items(payload)

        if not page_items:
            break

        items.extend(page_items)
        page += 1

    return items[:max_items]


def _trakt_trending(
    media_type: str,
    client_id: str,
    max_items: int = 100,
) -> List[Dict[str, Any]]:
    endpoint = "movies" if media_type == "movie" else "shows"
    headers = {
        "trakt-api-version": "2",
        "trakt-api-key": client_id,
    }

    payload = _get_json(
        f"{TRAKT_BASE}/{endpoint}/trending",
        headers=headers,  # type: ignore[arg-type]
    )
    items = _extract_items(payload)
    return items[:max_items]


def _cinemeta_catalog(
    catalog_id: str,
    media_type: str,
    max_items: int = 100,
) -> List[Dict[str, Any]]:
    media_path = "movie" if media_type == "movie" else "series"
    url = f"{STREMIO_BASE}/{media_path}/top.json"
    payload = _get_json(url)
    items = _extract_items(payload)

    if catalog_id == "top_rated":
        return items[:max_items]

    return items[:max_items]


def _request_config(request: Dict[str, Any], provider: str) -> Dict[str, Any]:
    providers = request.get("providers", {})
    config = providers.get(provider)

    if not isinstance(config, dict):
        raise ValueError(f"Provider '{provider}' is not configured for this request")

    return config


def _tmdb_api_key(request: Dict[str, Any], provider: str) -> str:
    config = _request_config(request, provider)
    api_key = config.get("api_key") or os.environ.get("TMDB_API_KEY")

    if not api_key:
        raise ValueError("Missing TMDB API key")

    return str(api_key)


def _trakt_client_id(request: Dict[str, Any], provider: str) -> str:
    config = _request_config(request, provider)
    client_id = config.get("client_id") or os.environ.get("TRAKT_CLIENT_ID")

    if not client_id:
        raise ValueError("Missing Trakt client ID")

    return str(client_id)


def _provider_request(request: Dict[str, Any], provider: str) -> Dict[str, Any]:
    config = _request_config(request, provider)
    media_type = str(config.get("media_type") or request.get("type") or "")

    if media_type not in {"movie", "series"}:
        raise ValueError(f"Unsupported media type: {media_type}")

    return {
        "list_id": str(config.get("list_id") or request.get("list_id") or ""),
        "media_type": media_type,
        "url": str(config.get("url") or ""),
        "max_items": int(config.get("max_items") or 100),
        "date_mode": str(config.get("date_mode") or "none"),
    }


def date_window(mode: str, today: date, media_type: str) -> tuple[str, date, date, str]:
    if mode == "recent":
        return (
            "release_date",
            today - timedelta(days=30),
            today,
            "primary_release_date.desc"
            if media_type == "movie"
            else "first_air_date.desc",
        )

    if mode == "future":
        return (
            "release_date",
            today,
            today + timedelta(days=180),
            "primary_release_date.asc"
            if media_type == "movie"
            else "first_air_date.asc",
        )

    raise ValueError(f"Unsupported date mode: {mode}")


def fetch_source(
    request: Dict[str, Any],
    provider: str,
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    config = _provider_request(request, provider)
    media_type = config["media_type"]
    list_id = config["list_id"]
    max_items = config["max_items"]

    if provider == "tmdb":
        api_key = _tmdb_api_key(request, provider)

        if config["date_mode"] in {"recent", "future"}:
            if today is None:
                today = date.today()

            field, start, end, order = date_window(
                config["date_mode"],
                today,
                media_type,
            )

            params = {
                "api_key": api_key,
                "page": 1,
                "include_adult": "false",
                "sort_by": order,
                "primary_release_date.gte"
                if media_type == "movie"
                else "first_air_date.gte": start.isoformat(),
                "primary_release_date.lte"
                if media_type == "movie"
                else "first_air_date.lte": end.isoformat(),
            }

            url = f"{TMDB_BASE}/discover/{'movie' if media_type == 'movie' else 'tv'}"
            payload = _get_json(url, params=params)
            items = _extract_items(payload)
        else:
            if list_id in {
                "popular_movies",
                "popular_series",
                "new_movies",
                "new_series",
                "upcoming_movies",
                "upcoming_series",
            }:
                items = _tmdb_list(list_id, media_type, api_key, max_items)
            else:
                items = _tmdb_search(
                    str(request.get("search", {}).get("title", "")),
                    media_type,
                    request.get("search", {}).get("year"),
                    api_key,
                )

    elif provider == "trakt":
        client_id = _trakt_client_id(request, provider)
        items = _trakt_trending(media_type, client_id, max_items)

    elif provider == "cinemeta":
        items = _cinemeta_catalog(list_id, media_type, max_items)

    else:
        url = config["url"]
        if not url:
            raise ValueError(f"Provider '{provider}' has no request URL")

        payload = _get_json(url)
        items = _extract_items(payload)

    return items[:max_items]


def _snapshot_filename(snapshot: SourceSnapshot) -> str:
    parts = [snapshot.request_id, snapshot.provider_id, snapshot.list_id]
    safe_parts = [re.sub(r"[^A-Za-z0-9_-]", "_", part) for part in parts]
    return "__".join(safe_parts) + ".json"


def save_snapshot(snapshot: SourceSnapshot, snapshot_dir: str | __import__("pathlib").Path) -> __import__("pathlib").Path:
    from pathlib import Path

    directory = Path(snapshot_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _snapshot_filename(snapshot)
    payload = {
        "request_id": snapshot.request_id,
        "provider_id": snapshot.provider_id,
        "list_id": snapshot.list_id,
        "media_type": snapshot.media_type,
        "fetched_at": snapshot.fetched_at,
        "items": snapshot.items,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        __import__("json").dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def load_snapshot(path: str | __import__("pathlib").Path) -> SourceSnapshot:
    import json
    from pathlib import Path

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return SourceSnapshot(
        request_id=str(payload["request_id"]),
        provider_id=str(payload["provider_id"]),
        list_id=str(payload["list_id"]),
        media_type=str(payload["media_type"]),
        fetched_at=str(payload["fetched_at"]),
        items=list(payload.get("items", [])),
    )
