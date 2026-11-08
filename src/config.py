"""Configuration loading and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ConfigurationError(ValueError):
    """Raised when catalogue configuration is invalid."""


def load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_config(config_dir: str | Path) -> dict[str, Any]:
    config_dir = Path(config_dir)
    sources = load_json(config_dir / "sources.json")
    rows = load_json(config_dir / "rows.json")
    ranking = load_json(config_dir / "ranking.json")

    if sources.get("schema_version") != 1:
        raise ConfigurationError("Unsupported sources schema")
    if rows.get("schema_version") != 1:
        raise ConfigurationError("Unsupported rows schema")
    if ranking.get("schema_version") != 1:
        raise ConfigurationError("Unsupported ranking schema")
    if ranking.get("algorithm") != "rrf":
        raise ConfigurationError("Only the rrf ranking algorithm is supported")

    providers = {provider["id"]: provider for provider in sources.get("providers", [])}
    request_ids: set[str] = set()

    for provider_id, provider in providers.items():
        if not provider.get("enabled"):
            continue
        for request in provider.get("requests", []):
            request_id = request.get("id")
            if not request_id:
                raise ConfigurationError(f"Missing request id for provider {provider_id}")
            if request_id in request_ids:
                raise ConfigurationError(f"Duplicate source request id: {request_id}")
            request_ids.add(request_id)

    for row in rows.get("rows", []):
        for list_id in row.get("source_lists", []):
            if list_id not in request_ids:
                raise ConfigurationError(f"Row {row.get('id')} references unknown list {list_id}")

    return {
        "sources": sources,
        "rows": rows,
        "ranking": ranking,
        "providers": providers,
    }
