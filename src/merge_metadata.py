"""Metadata merging with field provenance and release dates."""

from __future__ import annotations

from typing import Any

from .identity import media_identity


def merge_item(
    media_type: str,
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
    provider_id: str,
) -> dict[str, Any]:
    identity = media_identity(media_type, incoming)
    merged = dict(existing or {})
    merged.update({
        "id": identity["id"],
        "type": media_type,
        "ids": {
            "imdb": identity.get("imdb"),
            "tmdb": identity.get("tmdb"),
        },
    })

    field_sources = merged.setdefault("field_sources", {})

    for source_field, target_field in (
        ("name", "title"),
        ("title", "title"),
        ("poster", "poster"),
        ("background", "backdrop"),
        ("description", "overview"),
        ("releaseInfo", "year"),
        ("release_date", "release_date"),
        ("first_air_date", "release_date"),
        ("imdbRating", "rating"),
        ("tmdbRating", "rating"),
    ):
        value = incoming.get(source_field)
        if value in (None, "", []):
            continue
        if not merged.get(target_field):
            merged[target_field] = value
            field_sources[target_field] = provider_id

    return merged
