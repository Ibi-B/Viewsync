"""Configurable relevance and quality screening for discovery snapshots.

Ratings are confidence-adjusted. Low vote counts are uncertainty, not proof
that an upcoming title is poor.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _release_date(item: dict[str, Any], media_type: str) -> date | None:
    field = "release_date" if media_type == "movie" else "first_air_date"
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def bayesian_rating(
    vote_average: Any,
    vote_count: Any,
    *,
    prior: float = 6.0,
    prior_votes: float = 100.0,
) -> tuple[float, float]:
    """Return a confidence-adjusted rating on a 0-10 scale and vote confidence."""
    votes = max(0.0, _number(vote_count))
    rating = _number(vote_average, -1.0)
    if rating < 0.0 or rating > 10.0:
        rating = -1.0
    if votes <= 0.0 or rating < 0.0:
        return prior, 0.0
    confidence = votes / (votes + prior_votes)
    return ((confidence * rating) + ((1.0 - confidence) * prior), confidence)


def quality_score(item: dict[str, Any], policy: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    votes = max(0.0, _number(item.get("vote_count")))
    popularity = max(0.0, _number(item.get("popularity")))
    rating, confidence = bayesian_rating(
        item.get("vote_average"),
        votes,
        prior=_number(policy.get("rating_prior"), 6.0),
        prior_votes=_number(policy.get("rating_prior_votes"), 100.0),
    )
    overview_length = len(str(item.get("overview") or "").strip())
    has_poster = bool(item.get("poster_path"))
    has_backdrop = bool(item.get("backdrop_path"))
    score = (
        rating * 10.0
        + min(math.log1p(popularity) * 5.0, 30.0)
        + (8.0 if has_poster else 0.0)
        + min(overview_length / 20.0, 5.0)
        + (2.0 if has_backdrop else 0.0)
    )
    return round(score, 3), {
        "class": "established" if confidence >= 0.5 else "emerging",
        "score": round(score, 3),
        "bayesian_rating": round(rating, 3),
        "rating_confidence": round(confidence, 4),
        "vote_count": int(votes),
        "popularity": round(popularity, 4),
    }


def filter_snapshot_items(
    items: list[dict[str, Any]],
    policy: dict[str, Any],
    *,
    request_id: str,
    media_type: str,
    today: date,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Filter invalid, weakly supported and low-interest discovery candidates."""
    mode = str(policy.get("date_mode") or "none")
    min_popularity = max(0.0, _number(policy.get("min_popularity"), 0.0))
    min_overview = max(0, int(_number(policy.get("min_overview_length"), 25)))
    min_votes_for_rating = max(0, int(_number(policy.get("min_votes_for_rating"), 100)))
    min_bayesian_rating = _number(policy.get("min_bayesian_rating"), 5.0)
    require_poster = bool(policy.get("require_poster", True))
    exclude_video = bool(policy.get("exclude_video", True))
    exclude_adult = bool(policy.get("exclude_adult", False))
    max_future_days = max(0, int(_number(policy.get("max_future_days"), 180)))
    max_items = max(1, int(_number(policy.get("max_items"), 100)))

    exclusions: dict[str, int] = {}
    by_id: dict[str, dict[str, Any]] = {}

    def reject(reason: str) -> None:
        exclusions[reason] = exclusions.get(reason, 0) + 1

    for item in items:
        if not isinstance(item, dict):
            reject("invalid_record")
            continue
        media_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or item.get("name") or "").strip()
        if not media_id or not title:
            reject("missing_identity")
            continue
        if exclude_video and item.get("video") is True:
            reject("video_record")
            continue
        if exclude_adult and item.get("adult") is True:
            reject("adult_record")
            continue

        release = _release_date(item, media_type)
        if mode != "none" and release is None:
            reject("missing_or_invalid_release_date")
            continue
        if mode == "recent" and release is not None:
            if not (today - timedelta(days=30) <= release < today):
                reject("outside_recent_window")
                continue
        elif mode == "future" and release is not None:
            if not (today <= release <= today + timedelta(days=max_future_days)):
                reject("outside_upcoming_window")
                continue

        if require_poster and not item.get("poster_path"):
            reject("missing_poster")
            continue
        overview_length = len(str(item.get("overview") or "").strip())
        if overview_length < min_overview:
            reject("insufficient_overview")
            continue

        votes = max(0.0, _number(item.get("vote_count")))
        raw_rating = _number(item.get("vote_average"), -1.0)
        adjusted_rating, _ = bayesian_rating(
            raw_rating,
            votes,
            prior=_number(policy.get("rating_prior"), 6.0),
            prior_votes=_number(policy.get("rating_prior_votes"), 100.0),
        )
        if votes >= min_votes_for_rating and adjusted_rating < min_bayesian_rating:
            reject("low_confidence_adjusted_rating")
            continue

        popularity = max(0.0, _number(item.get("popularity")))
        if votes < min_votes_for_rating and popularity < min_popularity:
            reject("insufficient_interest_for_unrated_title")
            continue

        score, quality = quality_score(item, policy)
        item["_viewsync_quality"] = quality
        item["_viewsync_quality_score"] = score
        existing = by_id.get(media_id)
        if existing is None or score > _number(existing.get("_viewsync_quality_score")):
            by_id[media_id] = item

    accepted = sorted(
        by_id.values(),
        key=lambda item: (
            -_number(item.get("_viewsync_quality_score")),
            -_number(item.get("popularity")),
            str(item.get("id")),
        ),
    )[:max_items]
    return accepted, exclusions
