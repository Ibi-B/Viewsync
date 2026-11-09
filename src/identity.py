"""Media identity normalisation and conservative cross-provider matching."""

from __future__ import annotations

import re
from typing import Any, Dict


def normalise_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip()).casefold()


def normalise_title(value: Any) -> str:
    text = normalise_text(value)
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(the|a|an)\s+", "", text)
    return text


def normalise_year(value: Any) -> str | None:
    if value in (None, ""):
        return None
    match = re.search(r"\d{4}", str(value))
    return match.group(0) if match else None


def media_identity(media_type: str, meta: Dict[str, Any]) -> Dict[str, str]:
    imdb_id = meta.get("imdb_id") or meta.get("imdb")
    tmdb_id = meta.get("tmdb_id") or meta.get("tmdb")
    title = meta.get("name") or meta.get("title")
    year = meta.get("releaseInfo") or meta.get("year") or meta.get("release_date")

    identity: Dict[str, str] = {
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
        slug = normalise_title(title).replace(" ", "-") or "untitled"
        year_text = normalise_year(year) or "unknown"
        identity["id"] = f"{media_type}:title:{slug}:{year_text}"

    return identity


def _cross_id_match(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_title = normalise_title(left.get("title") or left.get("name"))
    right_title = normalise_title(right.get("title") or right.get("name"))

    if not left_title or left_title != right_title:
        return False

    left_year = normalise_year(
        left.get("releaseInfo") or left.get("year") or left.get("release_date")
    )
    right_year = normalise_year(
        right.get("releaseInfo") or right.get("year") or right.get("release_date")
    )

    return bool(left_year and right_year and left_year == right_year)


def same_media(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    if left.get("media_type") != right.get("media_type"):
        return False

    left_imdb = left.get("imdb")
    right_imdb = right.get("imdb")
    left_tmdb = left.get("tmdb")
    right_tmdb = right.get("tmdb")

    if left_imdb and right_imdb:
        return left_imdb == right_imdb

    if left_tmdb and right_tmdb:
        return left_tmdb == right_tmdb

    if (left_imdb and right_tmdb) or (left_tmdb and right_imdb):
        return _cross_id_match(left, right)

    return left.get("id") == right.get("id")


def resolve_identity(
    media_type: str,
    meta: Dict[str, Any],
    known_identities: Dict[str, Dict[str, Any]],
) -> str:
    """Return an existing canonical ID when this item is a conservative match."""

    identity = media_identity(media_type, meta)

    for existing_id, existing in known_identities.items():
        if same_media(identity, existing):
            return existing_id

    known_identities[identity["id"]] = identity
    return identity["id"]
