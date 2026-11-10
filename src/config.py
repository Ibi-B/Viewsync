"""Load and validate the current Viewsync catalogue configuration."""

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
    requests = load_json(config_dir / "requests.json")
    rows = load_json(config_dir / "rows.json")
    ranking = load_json(config_dir / "ranking.json")

    if not isinstance(sources, dict) or not isinstance(sources.get("providers"), dict):
        raise ConfigurationError("sources.json must define a providers object")
    if not isinstance(rows, dict) or not isinstance(rows.get("rows"), list):
        raise ConfigurationError("rows.json must define a rows array")
    if not isinstance(ranking, dict) or ranking.get("schema_version") != 1:
        raise ConfigurationError("Unsupported ranking schema")
    if ranking.get("algorithm") != "rrf":
        raise ConfigurationError("Only the rrf ranking algorithm is supported")
    if not isinstance(requests, list):
        raise ConfigurationError("requests.json must contain an array")

    providers = sources["providers"]
    request_ids: set[str] = set()
    for request in requests:
        if not isinstance(request, dict):
            raise ConfigurationError("Each source request must be an object")
        request_id = request.get("id")
        if not isinstance(request_id, str) or not request_id.strip():
            raise ConfigurationError("Each source request must have a non-empty id")
        if request_id in request_ids:
            raise ConfigurationError(f"Duplicate source request id: {request_id}")
        request_ids.add(request_id)

        configured = request.get("providers")
        if not isinstance(configured, dict) or not configured:
            raise ConfigurationError(f"Request {request_id} has no provider configuration")
        for provider_id, provider_request in configured.items():
            provider = providers.get(provider_id)
            if not isinstance(provider, dict):
                raise ConfigurationError(
                    f"Request {request_id} references unknown provider {provider_id}"
                )
            if not isinstance(provider_request, dict):
                raise ConfigurationError(
                    f"Request {request_id} has invalid configuration for {provider_id}"
                )
            list_id = provider_request.get("list_id") or request_id
            source_request = provider.get("requests", {}).get(list_id)
            if not isinstance(source_request, dict):
                raise ConfigurationError(
                    f"Request {request_id} references unknown {provider_id} list {list_id}"
                )
            media_type = provider_request.get("media_type") or source_request.get("media_type")
            if media_type not in {"movie", "series"}:
                raise ConfigurationError(
                    f"Request {request_id} has unsupported media type {media_type!r}"
                )
            if source_request.get("media_type") not in {None, media_type}:
                raise ConfigurationError(
                    f"Request {request_id} media type does not match {provider_id}.{list_id}"
                )

    row_ids: set[str] = set()
    for row in rows["rows"]:
        if not isinstance(row, dict):
            raise ConfigurationError("Each catalogue row must be an object")
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id.strip():
            raise ConfigurationError("Each catalogue row must have a non-empty id")
        if row_id in row_ids:
            raise ConfigurationError(f"Duplicate catalogue row id: {row_id}")
        row_ids.add(row_id)
        for list_id in row.get("source_lists", []):
            if list_id not in request_ids:
                raise ConfigurationError(
                    f"Row {row_id} references unknown source request {list_id}"
                )

    weights = ranking.get("provider_weights", {})
    if not isinstance(weights, dict):
        raise ConfigurationError("provider_weights must be an object")
    unknown_weights = set(weights) - set(providers)
    if unknown_weights:
        raise ConfigurationError(
            f"Ranking weights reference unknown providers: {sorted(unknown_weights)}"
        )

    return {
        "sources": sources,
        "requests": requests,
        "rows": rows,
        "ranking": ranking,
        "providers": providers,
    }
