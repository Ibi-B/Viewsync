"""Static release publication."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .validate import validate_release


def write_json(path: str | Path, data: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def publish_release(release: dict[str, Any], output_dir: str | Path) -> Path:
    validate_release(release)
    release_id = release["release_id"]
    release_dir = Path(output_dir) / "v1" / "releases" / release_id

    manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "published_at": release["published_at"],
        "ranking_version": release["ranking_version"],
        "rows": [],
    }

    for row in release["rows"]:
        row_id = row["id"]
        row_path = release_dir / "rows" / f"{row_id}.json"
        relative_path = row_path.relative_to(release_dir.parent.parent)

        published_row = {
            "id": row_id,
            "title": row["title"],
            "path": str(relative_path),
            "data_updated_at": row["data_updated_at"],
            "status": row["status"],
            "configured_provider_count": row["configured_provider_count"],
            "contributing_provider_count": row["contributing_provider_count"],
        }
        manifest["rows"].append(published_row)

        write_json(
            row_path,
            {
                "id": row_id,
                "title": row["title"],
                "media_type": row["media_type"],
                "data_updated_at": row["data_updated_at"],
                "status": row["status"],
                "items": row["items"],
            },
        )

        for item in row["items"]:
            item_id = item["id"].replace(":", "_")
            details = {
                "id": item["id"],
                "type": item["type"],
                "title": item.get("title"),
                "year": item.get("year"),
                "poster": item.get("poster"),
                "backdrop": item.get("backdrop"),
                "overview": item.get("overview"),
                "field_sources": item.get("field_sources", {}),
            }
            write_json(release_dir / "items" / f"{item_id}.json", details)

    manifest_path = release_dir / "manifest.json"
    write_json(manifest_path, manifest)
    return manifest_path
