"""Validation helpers for source snapshots and generated releases."""

from __future__ import annotations

from typing import Any

from .fetch import SourceSnapshot


class ValidationError(ValueError):
    """Raised when data fails validation."""


def validate_snapshot(snapshot: SourceSnapshot) -> None:
    if not snapshot.request_id or not snapshot.provider_id or not snapshot.list_id:
        raise ValidationError("Snapshot is missing required identity fields")
    if snapshot.media_type not in {"movie", "series"}:
        raise ValidationError(f"Unsupported media type: {snapshot.media_type}")
    if not isinstance(snapshot.items, list):
        raise ValidationError("Snapshot items must be a list")


def has_usable_items(snapshot: SourceSnapshot) -> bool:
    return bool(snapshot.items)


def validate_release(release: dict[str, Any]) -> None:
    if release.get("schema_version") != 1:
        raise ValidationError("Unsupported release schema")
    if not release.get("release_id"):
        raise ValidationError("Release is missing release_id")
    if not release.get("rows"):
        raise ValidationError("Release has no rows")

    for row in release["rows"]:
        if not row.get("id") or not row.get("path"):
            raise ValidationError("Row is missing id or path")
        if not isinstance(row.get("items"), list):
            raise ValidationError(f"Row {row['id']} has no item array")
