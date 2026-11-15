import copy
import json

import pytest

from src.config import ConfigurationError, load_config


def _write_config(tmp_path, *, sources=None, requests=None):
    config = {
        "sources": sources
        or {
            "schema_version": 1,
            "providers": [
                {
                    "id": "tmdb",
                    "enabled": True,
                    "requests": [{"id": "popular_movies"}],
                },
                {
                    "id": "trakt",
                    "enabled": False,
                    "requests": [{"id": "trending_movies"}],
                },
            ],
        },
        "requests": requests
        if requests is not None
        else [
            {
                "id": "popular_movies",
                "providers": {
                    "tmdb": {
                        "list_id": "popular_movies",
                        "media_type": "movie",
                    }
                },
            }
        ],
        "rows": {
            "schema_version": 1,
            "rows": [
                {
                    "id": "popular-movies",
                    "source_lists": ["popular_movies"],
                }
            ],
        },
        "ranking": {"schema_version": 1, "algorithm": "rrf"},
    }

    for name, payload in config.items():
        (tmp_path / f"{name}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )


def test_load_config_validates_and_returns_request_definitions(tmp_path):
    _write_config(tmp_path)

    config = load_config(tmp_path)

    assert [request["id"] for request in config["requests"]] == ["popular_movies"]
    assert config["requests"][0]["providers"]["tmdb"]["list_id"] == "popular_movies"


def test_rejects_request_id_missing_from_sources(tmp_path):
    _write_config(
        tmp_path,
        requests=[
            {
                "id": "unknown_request",
                "providers": {
                    "tmdb": {"list_id": "popular_movies", "media_type": "movie"}
                },
            }
        ],
    )

    with pytest.raises(ConfigurationError, match="Unknown request id"):
        load_config(tmp_path)


def test_rejects_unknown_provider_id(tmp_path):
    _write_config(
        tmp_path,
        requests=[
            {
                "id": "popular_movies",
                "providers": {
                    "missing_provider": {
                        "list_id": "popular_movies",
                        "media_type": "movie",
                    }
                },
            }
        ],
    )

    with pytest.raises(ConfigurationError, match="unknown provider"):
        load_config(tmp_path)


def test_rejects_references_to_disabled_providers(tmp_path):
    _write_config(
        tmp_path,
        requests=[
            {
                "id": "trending_movies",
                "providers": {
                    "trakt": {
                        "list_id": "trending_movies",
                        "media_type": "movie",
                    }
                },
            }
        ],
    )

    with pytest.raises(ConfigurationError, match="disabled provider"):
        load_config(tmp_path)


def test_rejects_unknown_provider_list_id(tmp_path):
    _write_config(
        tmp_path,
        requests=[
            {
                "id": "popular_movies",
                "providers": {
                    "tmdb": {
                        "list_id": "not_configured",
                        "media_type": "movie",
                    }
                },
            }
        ],
    )

    with pytest.raises(ConfigurationError, match="unknown list"):
        load_config(tmp_path)


def test_rejects_duplicate_request_ids(tmp_path):
    request = {
        "id": "popular_movies",
        "providers": {
            "tmdb": {"list_id": "popular_movies", "media_type": "movie"}
        },
    }
    _write_config(tmp_path, requests=[copy.deepcopy(request), copy.deepcopy(request)])

    with pytest.raises(ConfigurationError, match="Duplicate request id"):
        load_config(tmp_path)


def test_rejects_duplicate_source_request_ids_across_providers(tmp_path):
    sources = {
        "schema_version": 1,
        "providers": [
            {
                "id": "tmdb",
                "enabled": True,
                "requests": [{"id": "popular_movies"}],
            },
            {
                "id": "trakt",
                "enabled": False,
                "requests": [{"id": "popular_movies"}],
            },
        ],
    }
    _write_config(tmp_path, sources=sources)

    with pytest.raises(ConfigurationError, match="Duplicate source request id"):
        load_config(tmp_path)


def test_rejects_duplicate_provider_ids(tmp_path):
    sources = {
        "schema_version": 1,
        "providers": [
            {
                "id": "tmdb",
                "enabled": True,
                "requests": [{"id": "popular_movies"}],
            },
            {
                "id": "tmdb",
                "enabled": True,
                "requests": [{"id": "another_list"}],
            },
        ],
    }
    _write_config(tmp_path, sources=sources)

    with pytest.raises(ConfigurationError, match="Duplicate provider id"):
        load_config(tmp_path)



def test_rejects_request_id_bound_only_to_another_provider(tmp_path):
    _write_config(
        tmp_path,
        requests=[
            {
                "id": "trending_movies",
                "providers": {
                    "tmdb": {
                        "list_id": "popular_movies",
                        "media_type": "movie",
                    }
                },
            }
        ],
    )

    with pytest.raises(ConfigurationError, match="not defined for any configured provider"):
        load_config(tmp_path)
