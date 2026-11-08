"""Source fetching and snapshot persistence."""

from __future__ import annotations

import hashlib
import json
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


def fetch_source(request: dict[str, Any], provider: dict[str, Any]) -> SourceSnapshot:
    payload = fetch_json(
        request["url"],
        timeout_seconds=float(request.get("timeout_seconds", 20)),
    )

    metas = payload.get("metas")
    if not isinstance(metas, list):
        raise FetchError(f"Source {request['id']} did not return a metas array")

    max_items = int(request.get("max_items", 100))
    items = []
    for index, meta in enumerate(metas[:max_items], start=1):
        if not isinstance(meta, dict):
            continue
        item = dict(meta)
        item["source_rank"] = index
        items.append(item)

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
