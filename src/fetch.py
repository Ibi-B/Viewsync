"""Source fetching and snapshot persistence."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .http_client import FetchError, fetch_json


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class SourceSnapshot:
    request_id: str
    provider_id: str
    list_id: str
    media_type: str
    url: str
    fetched_at: str
    items: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def snapshot_fingerprint(snapshot: SourceSnapshot) -> str:
    payload = json.dumps(snapshot.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def apply_authentication(url: str, auth: dict[str, Any] | None) -> str:
    if not auth:
        return url

    if auth.get("type") != "api_key":
        raise FetchError(f"Unsupported authentication type: {auth.get('type')}")

    environment_variable = auth.get("env")
    if not environment_variable:
        raise FetchError("API-key authentication requires an environment variable")

    api_key = os.environ.get(environment_variable)
    if not api_key:
        raise FetchError(f"Missing required environment variable: {environment_variable}")

    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    query["api_key"] = api_key
    return parsed._replace(query=urllib.parse.urlencode(query)).geturl()


def normalise_tmdb_item(media_type: str, result: dict[str, Any]) -> dict[str, Any]:
    title = result.get("title") or result.get("name")
    release_date = result.get("release_date") or result.get("first_air_date")

    item = {
        "imdb_id": None,
        "tmdb_id": result.get("id"),
        "name": title,
        "poster": f"https://image.tmdb.org/t/p/w500{result['poster_path']}" if result.get("poster_path") else None,
        "background": f"https://image.tmdb.org/t/p/w1280{result['backdrop_path']}" if result.get("backdrop_path") else None,
        "description": result.get("overview"),
        "releaseInfo": release_date,
        "release_date": release_date,
        "tmdbRating": result.get("vote_average"),
    }
    return {key: value for key, value in item.items() if value is not None}


def fetch_source(request: dict[str, Any], provider: dict[str, Any]) -> SourceSnapshot:
    url = apply_authentication(request["url"], request.get("auth"))
    payload = fetch_json(
        url,
        timeout_seconds=float(request.get("timeout_seconds", 20)),
    )

    if provider["id"] == "tmdb":
        raw_items = payload.get("results")
    else:
        raw_items = payload.get("metas")

    if not isinstance(raw_items, list):
        raise FetchError(f"Source {request['id']} did not return an item array")

    max_items = int(request.get("max_items", 100))
    items = []

    for index, raw_item in enumerate(raw_items[:max_items], start=1):
        if not isinstance(raw_item, dict):
            continue

        if provider["id"] == "tmdb":
            meta = normalise_tmdb_item(request["media_type"], raw_item)
        else:
            meta = dict(raw_item)

        meta["source_rank"] = index
        items.append(meta)

    return SourceSnapshot(
        request_id=request["id"],
        provider_id=provider["id"],
        list_id=request["list_id"],
        media_type=request["media_type"],
        url=request["url"],
        fetched_at=utc_now(),
        items=items,
    )


def load_snapshot(path: str | Path) -> SourceSnapshot:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return SourceSnapshot(**data)


def save_snapshot(snapshot: SourceSnapshot, directory: str | Path) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{snapshot.request_id}.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(snapshot.to_dict(), handle, ensure_ascii=False, indent=2)
    return path
