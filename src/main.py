import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .fetch import fetch_source

CONFIG = Path("catalog-config")
PUBLIC = Path("public")
STATE = Path("state")


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
            "provenance": row.get("provenance", {}),
            "availability": row.get("availability", "metadata-only"),
            "actions": row.get("actions", []),
            "previewPolicy": row.get("previewPolicy", "off"),
        }

        metas.append(row_config)

    return {"metas": metas}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the Viewsync catalogue")
    parser.add_argument("--config", default="catalog-config")
    parser.add_argument("--output", default="public")
    parser.add_argument("--state", default="state")
    return parser.parse_args()


def main() -> None:
    global CONFIG, PUBLIC, STATE

    args = parse_args()
    CONFIG = Path(args.config)
    PUBLIC = Path(args.output)
    STATE = Path(args.state)

    now = datetime.now(timezone.utc)
    rows = load_json(CONFIG / "rows.json")["rows"]
    catalog = build_catalog(rows, now)
    write_json(PUBLIC / "catalog.json", catalog)


if __name__ == "__main__":
    main()