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
        providers: dict[str, dict[str, Any]] = {}
        for provider_id, provider in raw_providers.items():
            if not provider_id or not isinstance(provider, dict):
                raise ConfigurationError(f"Provider {provider_id} must be an object")
            providers[str(provider_id)] = {**provider, "id": str(provider_id)}
        return providers

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
        request_ids: list[str] = []
        for request in requests:
            if not isinstance(request, dict) or not request.get("id"):
                raise ConfigurationError(
                    f"Missing request id for provider {provider.get('id')}"
                )
            request_ids.append(str(request["id"]))
        return request_ids
    raise ConfigurationError(
        f"Provider {provider.get('id')} requests must be an object or an array"
    )


def _validate_requests(
    raw_requests: Any,
    providers: dict[str, dict[str, Any]],
    source_request_ids: dict[str, set[str]],
    all_source_request_ids: set[str],
) -> list[dict[str, Any]]:
    """Ensure every configured request resolves to an enabled source definition."""
    if not isinstance(raw_requests, list):
        raise ConfigurationError("Requests configuration must be an array")

    validated: list[dict[str, Any]] = []
    seen_request_ids: set[str] = set()

    for request in raw_requests:
        if not isinstance(request, dict) or not request.get("id"):
            raise ConfigurationError("Each request must be an object with an id")

        request_id = str(request["id"])
        if request_id in seen_request_ids:
            raise ConfigurationError(f"Duplicate request id: {request_id}")
        seen_request_ids.add(request_id)

        if request_id not in all_source_request_ids:
            raise ConfigurationError(f"Unknown request id: {request_id}")

        request_providers = request.get("providers", {})
        if not isinstance(request_providers, dict) or not request_providers:
            raise ConfigurationError(
                f"Request {request_id} must configure at least one provider"
            )

        request_id_matches_provider = False
        for provider_id, provider_config in request_providers.items():
            provider_id = str(provider_id)
            if provider_id not in providers:
                raise ConfigurationError(
                    f"Request {request_id} references unknown provider {provider_id}"
                )

            provider = providers[provider_id]
            if provider.get("enabled") is False:
                raise ConfigurationError(
                    f"Request {request_id} references disabled provider {provider_id}"
                )

            if not isinstance(provider_config, dict):
                raise ConfigurationError(
                    f"Request {request_id} provider {provider_id} must be an object"
                )

            if request_id in source_request_ids[provider_id]:
                request_id_matches_provider = True

            list_id = str(provider_config.get("list_id") or request_id)
            if list_id not in source_request_ids[provider_id]:
                raise ConfigurationError(
                    f"Request {request_id} references unknown list {list_id} "
                    f"for provider {provider_id}"
                )

        if not request_id_matches_provider:
            raise ConfigurationError(
                f"Request id {request_id} is not defined for any configured provider"
            )

        validated.append(request)

    return validated


def load_config(config_dir: str | Path) -> dict[str, Any]:
    config_dir = Path(config_dir)
    sources = load_json(config_dir / "sources.json")
    requests = load_json(config_dir / "requests.json")
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
    source_request_ids: dict[str, set[str]] = {}

    for provider_id, provider in providers.items():
        provider_ids = _request_ids(provider)
        provider_request_ids = set(provider_ids)
        if len(provider_request_ids) != len(provider_ids):
            raise ConfigurationError(
                f"Duplicate source request id for provider {provider_id}"
            )
        duplicates = request_ids.intersection(provider_request_ids)
        if duplicates:
            duplicate_id = sorted(duplicates)[0]
            raise ConfigurationError(f"Duplicate source request id: {duplicate_id}")
        request_ids.update(provider_request_ids)
        source_request_ids[provider_id] = provider_request_ids

    enabled_request_ids = {
        request_id
        for provider_id, provider_ids in source_request_ids.items()
        if providers[provider_id].get("enabled") is not False
        for request_id in provider_ids
    }

    validated_requests = _validate_requests(
        requests,
        providers,
        source_request_ids,
        request_ids,
    )

    for row in rows.get("rows", []):
        for list_id in row.get("source_lists", []):
            if list_id not in enabled_request_ids:
                raise ConfigurationError(
                    f"Row {row.get('id')} references unknown or disabled list {list_id}"
                )

    return {
        "sources": sources,
        "requests": validated_requests,
        "rows": rows,
        "ranking": ranking,
        "providers": providers,
    }
