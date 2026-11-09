"""Media identity normalisation."""

from __future__ import annotations

import re
from typing import Any


def normalise_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip()).casefold()


def media_identity(media_type: str, meta: dict[str, Any]) -> dict[str, str]:
    imdb_id = meta.get("imdb_id") or meta.get("imdb")
    tmdb_id = meta.get("tmdb_id") or meta.get("tmdb")
    title = meta.get("name") or meta.get("title")
    year = meta.get("releaseInfo") or meta.get("year")

    identity: dict[str, str] = {
        "media_type": media_type,
    }

    if imdb_id:
        identity["imdb"] = str(imdb_id)
    if tmdb_id:
        identity["tmdb"] = str(tmdb_id)

    if identity.get("imdb"):
        identity["id"] = f"{media_type}:imdb:{identity['imdb']}"
    elif identity.get("tmdb"):
        identity["id"] = f"{media_type}:tmdb:{identity['tmdb']}"
    else:
        slug = normalise_text(title).replace(" ", "-") or "untitled"
        year_text = normalise_text(year).replace(" ", "-") or "unknown"
        identity["id"] = f"{media_type}:title:{slug}:{year_text}"

    return identity


def identity_confidence(identity: dict[str, str]) -> str:
    if identity.get("imdb") or identity.get("tmdb"):
        return "exact-id"

    identity_id = identity.get("id", "")

    if ":title:" in identity_id and not identity_id.endswith(":unknown"):
        return "title-year"

    return "unresolved"


def same_media(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("media_type") != right.get("media_type"):
        return False

    for key in ("imdb", "tmdb"):
        if left.get(key) and right.get(key):
            return left[key] == right[key]

    return left.get("id") == right.get("id")