"""Viewsync catalogue generation entry point."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_config
from .fetch import SourceSnapshot, fetch_source
from .manifest import build_release
from .publish import publish_release
from .state import persist_snapshots, preserve_last_good_release
from .validate import validate_release

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / "catalog-config"
OUTPUT = BASE / "dist"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _fetch_snapshots(
    config_dir: Path,
    now: datetime,
) -> list[SourceSnapshot]:
    requests = load_json(config_dir / "requests.json")
    snapshots: list[SourceSnapshot] = []

    for request in requests:
        request_id = str(request.get("id") or "")
        if not request_id:
            continue

        for provider_id, provider_config in request.get("providers", {}).items():
            try:
                items = fetch_source(request, provider_id, now.date())
            except Exception as exc:
                print(f"Fetch failed for {request_id}/{provider_id}: {exc}")
                continue

            snapshots.append(
                SourceSnapshot(
                    request_id=request_id,
                    provider_id=provider_id,
                    list_id=str(provider_config.get("list_id") or request_id),
                    media_type=str(provider_config.get("media_type") or ""),
                    fetched_at=now.isoformat(),
                    items=items,
                )
            )

    return snapshots


def generate_catalog(
    config_dir: str | Path = CONFIG,
    output_dir: str | Path = OUTPUT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Generate, validate, publish, and point to the current catalogue release."""

    now = now or datetime.now(timezone.utc)
    config_dir = Path(config_dir)
    output_dir = Path(output_dir)
    state_dir = output_dir / "state"

    config = load_config(config_dir)
    snapshots = _fetch_snapshots(config_dir, now)

    if not snapshots:
        raise ValueError("No provider snapshots were available; refusing to publish a release")

    persist_snapshots(snapshots, state_dir)
    preserve_last_good_release(state_dir, output_dir)

    release = build_release(config["rows"]["rows"], snapshots, now)

    if not release["rows"]:
        raise ValueError("No catalogue rows could be generated from available snapshots")

    validate_release(release)
    publish_release(release, output_dir)

    current = {
        "schema_version": 1,
        "release_id": release["release_id"],
        "manifest_path": "v1/manifest.json",
        "generated_at": release["generated_at"],
        "ranking_version": release["ranking_version"],
        "status": "current",
    }
    write_json(output_dir / "v1" / "current.json", current)

    return release


def main() -> None:
    generate_catalog()


if __name__ == "__main__":
    main()
