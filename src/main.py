import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fetch import fetch_source
from manifest import build_manifest

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / "catalog-config"
PUBLIC = BASE / "public"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")


def build_catalog(rows: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    request_configs = {
        request["id"]: request
        for request in load_json(CONFIG / "requests.json")
    }

    request_providers = {
        request["id"]: request.get("providers", [])
        for request in load_json(CONFIG / "requests.json")
    }

    metas = []

    for row in rows:
        source_lists = row.get("source_lists", [])
        request_items = []

        for source_id in source_lists:
            request = request_configs.get(source_id)

            if not request:
                continue

            providers = request_providers.get(source_id, [])

            for provider in providers:
                try:
                    items = fetch_source(request, provider, now.date())
                except Exception as exc:
                    print(f"Fetch failed for {source_id}/{provider}: {exc}")
                    continue

                request_items.extend(items)

        if not request_items:
            continue

        row_config = {
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "source_lists": source_lists,
            "extra": row.get("extra", []),
            "date_field": row.get("date_field"),
            "date_mode": row.get("date_mode", "none"),
        }

        metas.append(row_config)

    return {"metas": metas}


def main() -> None:
    now = datetime.now(timezone.utc)
    rows = load_json(CONFIG / "rows.json")
    catalog = build_catalog(rows, now)
    write_json(PUBLIC / "catalog.json", catalog)


if __name__ == "__main__":
    main()
