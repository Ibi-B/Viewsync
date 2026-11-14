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


def _provider_map(raw_providers: Any) -> dict[str, dict[str, Any]]:
    """Normalise supported provider-map and provider-list configuration shapes."""
    if isinstance(raw_providers, dict):
        return {
            str(provider_id): {"id": str(provider_id), **provider}
            for provider_id, provider in raw_providers.items()
            if isinstance(provider, dict)
        }

    if isinstance(raw_providers, list):
        providers: dict[str, dict[str, Any]] = {}
        for provider in raw_providers:
            if not isinstance(provider, dict) or not provider.get("id"):
                raise ConfigurationError("Each provider must be an object with an id")
            provider_id = str(provider["id"])
            if provider_id in providers:
                raise ConfigurationError(f"Duplicate provider id: {provider_id}")
            providers[provider_id] = provider
        return providers

    raise ConfigurationError("Providers must be an object or an array")


def _request_ids(provider: dict[str, Any]) -> list[str]:
    requests = provider.get("requests", {})
    if isinstance(requests, dict):
        return [str(request_id) for request_id in requests]
    if isinstance(requests, list):
        return [
            str(request["id"])
            for request in requests
            if isinstance(request, dict) and request.get("id")
        ]
    raise ConfigurationError(
        f"Provider {provider.get('id')} requests must be an object or an array"
    )


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

    providers = _provider_map(sources.get("providers", {}))
    request_ids: set[str] = set()

    for provider_id, provider in providers.items():
        for request_id in _request_ids(provider):
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
