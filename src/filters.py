"""Catalogue relevance and quality filtering.

Adult content is intentionally not filtered.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any


class FilterError(ValueError):
    """Raised when filter configuration or inputs are invalid."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_title(value: Any) -> str:
    value = _text(value).lower()
    return re.sub(r"\s+", " ", value)


def _release_date(value: Any) -> date | None:
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def relevance_score(item: dict[str, Any]) -> float:
    vote_count = _number(item.get("vote_count"))
    popularity = _number(item.get("popularity"))
    overview = _text(item.get("overview"))

    score = 0.0
    score += min(vote_count / 10.0, 30.0)
    score += min(popularity, 25.0)
    score += 10.0 if item.get("poster_path") else -30.0
    score += 5.0 if item.get("backdrop_path") else 0.0
    score += min(len(overview) / 20.0, 10.0)
    score += 10.0 if _release_date(item.get("release_date") or item.get("first_air_date")) else -20.0
    score -= 40.0 if item.get("video") else 0.0
    return round(score, 2)


def filter_snapshot_items(
    items: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    request_id: str,
    today: date,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Apply quality and relevance filters to one snapshot's items."""
    if not isinstance(items, list):
        raise FilterError(f"Snapshot items for {request_id!r} must be a list")

    min_score = _number(config.get("minRelevanceScore"), 20.0)
    min_votes = _number(config.get("minVoteCount"), 10.0)
    top_rated_votes = _number(config.get("topRatedMinVoteCount"), 100.0)
    min_overview = int(_number(config.get("minOverviewLength"), 40.0))
    require_poster = bool(config.get("requirePoster", True))
    max_future_days = int(_number(config.get("maxFutureDays"), 365.0))
    exclude_video = bool(config.get("excludeVideo", True))

    request_lower = request_id.lower()
    is_top_rated = "top" in request_lower and "rated" in request_lower
    is_upcoming = "upcoming" in request_lower
    is_new = "new" in request_lower or "now_playing" in request_lower
    is_trending = "trending" in request_lower

    accepted: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            exclusions.append({"index": str(index), "reason": "invalidRecord"})
            continue

        media_id = _text(item.get("id"))
        title = _text(item.get("title") or item.get("name"))

        if not media_id or not title:
            exclusions.append({"index": str(index), "reason": "missingIdOrTitle"})
            continue

        if exclude_video and item.get("video"):
            exclusions.append({"index": str(index), "reason": "video"})
            continue

        if require_poster and not item.get("poster_path"):
            exclusions.append({"index": str(index), "reason": "missingPoster"})
            continue

        release = _release_date(item.get("release_date") or item.get("first_air_date"))
        if not release:
            exclusions.append({"index": str(index), "reason": "missingReleaseDate"})
            continue

        if is_upcoming and release > today + timedelta(days=max_future_days):
            exclusions.append({"index": str(index), "reason": "futureBeyondHorizon"})
            continue

        vote_count = _number(item.get("vote_count"))
        if (is_new or is_trending) and vote_count < min_votes:
            exclusions.append({"index": str(index), "reason": "lowVoteCount"})
            continue

        if is_top_rated and vote_count < top_rated_votes:
            exclusions.append({"index": str(index), "reason": "lowVoteCount"})
            continue

        overview = _text(item.get("overview"))
        score = relevance_score(item)

        if len(overview) < min_overview:
            score -= 15.0

        if score < min_score:
            exclusions.append({"index": str(index), "reason": "lowRelevanceScore"})
            continue

        item["_viewsync_relevance_score"] = score
        accepted.append(item)

    return accepted, exclusions


def deduplicate_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Retain one canonical record per TMDB ID and normalized title/year."""
    by_id: dict[str, dict[str, Any]] = {}
    by_title_year: dict[str, dict[str, Any]] = {}
    accepted: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []

    def stronger(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
        return candidate.get("_viewsync_relevance_score", 0) > existing.get("_viewsync_relevance_score", 0)

    for index, item in enumerate(items):
        media_id = _text(item.get("id"))
        title = _normalized_title(item.get("title") or item.get("name"))
        release = _release_date(item.get("release_date") or item.get("first_air_date"))
        title_year = f"{title}:{release.year if release else 'unknown'}"

        if media_id in by_id:
            exclusions.append({"index": str(index), "reason": "duplicateTmdbId"})
            continue

        existing = by_title_year.get(title_year)
        if existing:
            if stronger(existing, item):
                accepted.remove(existing)
                accepted.append(item)
                by_title_year[title_year] = item
                exclusions.append({"index": str(index), "reason": "duplicateTitleYear"})
            else:
                exclusions.append({"index": str(index), "reason": "duplicateTitleYear"})
            continue

        by_id[media_id] = item
        by_title_year[title_year] = item
        accepted.append(item)

    return accepted, exclusions


def build_filter_report(
    total: int,
    accepted: list[dict[str, Any]],
    exclusions: list[dict[str, str]],
) -> dict[str, Any]:
    reasons: dict[str, int] = {}
    for exclusion in exclusions:
        reason = exclusion["reason"]
        reasons[reason] = reasons.get(reason, 0) + 1

    return {
        "totalRecords": total,
        "published": len(accepted),
        "excluded": len(exclusions),
        "reasons": reasons,
        "exclusions": exclusions,
    }
