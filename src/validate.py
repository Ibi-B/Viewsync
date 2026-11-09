"""Validation helpers for source snapshots and generated releases."""

from __future__ import annotations

import math
from typing import Any

from .fetch import SourceSnapshot


class ValidationError(ValueError):
    """Raised when data fails validation."""


MEDIA_KINDS = {"movie", "series", "live_tv", "radio"}
FRESHNESS_STATUSES = {"fresh", "retained_full", "retained_declining", "expired"}


def validate_snapshot(snapshot: SourceSnapshot) -> None:
    if not snapshot.request_id or not snapshot.provider_id or not snapshot.list_id:
        raise ValidationError("Snapshot is missing required identity fields")
    if snapshot.media_type not in {"movie", "series"}:
        raise ValidationError(f"Unsupported media type: {snapshot.media_type}")
    if not isinstance(snapshot.items, list):
        raise ValidationError("Snapshot items must be a list")


def has_usable_items(snapshot: SourceSnapshot) -> bool:
    return bool(snapshot.items)


def _validate_url(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        raise ValidationError(f"{field} must be an HTTP or HTTPS URL")


def _validate_positive_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field} must be numeric")

    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValidationError(f"{field} must be finite and positive")
    return number


def _validate_positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError(f"{field} must be a positive integer")
    return value


def _validate_source_attribution(attribution: Any, context: str) -> None:
    if not isinstance(attribution, list) or not attribution:
        raise ValidationError(f"{context} source_attribution must be a non-empty array")

    for entry in attribution:
        if not isinstance(entry, dict):
            raise ValidationError(f"{context} source attribution entries must be objects")

        for key in ("provider_id", "list_id", "rank", "weight", "fetched_at", "freshness"):
            if key not in entry:
                raise ValidationError(f"{context} source attribution is missing {key}")

        if not entry["provider_id"] or not entry["list_id"]:
            raise ValidationError(f"{context} source attribution is missing provider identity")

        if not isinstance(entry["fetched_at"], str) or not entry["fetched_at"]:
            raise ValidationError(f"{context} source attribution has invalid fetched_at")

        if entry["freshness"] not in FRESHNESS_STATUSES:
            raise ValidationError(f"{context} has invalid freshness {entry['freshness']!r}")

        _validate_positive_integer(entry["rank"], f"{context} attribution rank")
        _validate_positive_number(entry["weight"], f"{context} attribution weight")


def validate_release(release: dict[str, Any]) -> None:
    if release.get("schema_version") != 2:
        raise ValidationError("Unsupported release schema; expected schema_version 2")
    if not release.get("release_id"):
        raise ValidationError("Release is missing release_id")
    if not release.get("generated_at"):
        raise ValidationError("Release is missing generated_at")
    if not release.get("ranking_version"):
        raise ValidationError("Release is missing ranking_version")

    freshness = release.get("catalog_freshness")
    if not isinstance(freshness, dict) or freshness.get("status") not in {
        "fresh",
        "mixed",
        "retained",
        "expired",
    }:
        raise ValidationError("Release has invalid catalog_freshness")

    for field in ("oldest_source_age_hours", "newest_source_age_hours"):
        value = freshness.get(field)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValidationError(f"catalog_freshness.{field} must be numeric")
            if value < 0:
                raise ValidationError(f"catalog_freshness.{field} cannot be negative")

    rows = release.get("rows")
    if not rows:
        raise ValidationError("Release has no rows")

    for row in rows:
        if not row.get("id"):
            raise ValidationError("Row is missing id")

        media_kind = row.get("media_kind")
        if media_kind not in MEDIA_KINDS:
            raise ValidationError(f"Row {row['id']} has invalid media_kind {media_kind!r}")

        items = row.get("items")
        if not isinstance(items, list):
            raise ValidationError(f"Row {row['id']} has no item array")

        for item in items:
            if not isinstance(item, dict):
                raise ValidationError(f"Row {row['id']} contains a non-object item")

            if not item.get("id"):
                raise ValidationError(f"Row {row['id']} contains an item without id")

            item_kind = item.get("media_kind")
            if item_kind not in MEDIA_KINDS:
                raise ValidationError(
                    f"Row {row['id']} item {item.get('id')!r} has invalid media_kind"
                )

            if not item.get("title"):
                raise ValidationError(f"Item {item.get('id')!r} is missing title")

            images = item.get("images")
            if not isinstance(images, dict):
                raise ValidationError(f"Item {item.get('id')!r} has invalid images")

            _validate_url(images.get("poster"), f"Item {item.get('id')!r} poster")
            _validate_url(images.get("backdrop"), f"Item {item.get('id')!r} backdrop")
            _validate_url(images.get("logo"), f"Item {item.get('id')!r} logo")

            metadata = item.get("metadata")
            if not isinstance(metadata, dict):
                raise ValidationError(f"Item {item.get('id')!r} has invalid metadata")

            _validate_source_attribution(
                item.get("source_attribution"),
                f"Item {item.get('id')!r}",
            )

            ranking = item.get("ranking")
            if not isinstance(ranking, dict):
                raise ValidationError(f"Item {item.get('id')!r} has invalid ranking")
