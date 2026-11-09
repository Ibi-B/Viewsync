"""Validation helpers for source snapshots and generated releases."""

from __future__ import annotations

from typing import Any

from .fetch import SourceSnapshot


class ValidationError(ValueError):
    """Raised when data fails validation."""


_ALLOWED_AVAILABILITY = {
    'metadata-only',
    'requires-source-selection',
    'playable',
    'unavailable',
}
_ALLOWED_PREVIEW = {'off', 'focused', 'reduced-data'}
_ALLOWED_CONFIDENCE = {'exact-id', 'title-year', 'unresolved'}


def validate_snapshot(snapshot: SourceSnapshot) -> None:
    if not snapshot.request_id or not snapshot.provider_id or not snapshot.list_id:
        raise ValidationError("Snapshot is missing required identity fields")
    if snapshot.media_type not in {"movie", "series"}:
        raise ValidationError(f"Unsupported media type: {snapshot.media_type}")
    if not isinstance(snapshot.items, list):
        raise ValidationError("Snapshot items must be list")


def has_usable_items(snapshot: SourceSnapshot) -> bool:
    return bool(snapshot.items)


def _validate_home_contract(payload, label):
    if 'availability' in payload and payload['availability'] not in _ALLOWED_AVAILABILITY:
        raise ValidationError(f"{label} has unsupported availability: {payload['availability']}")
    if 'actions' in payload:
        actions = payload['actions']
        if not isinstance(actions, list) or not all(isinstance(action, str) for action in actions):
            raise ValidationError(f"{label} has invalid actions")
    if 'previewPolicy' in payload and payload['previewPolicy'] not in _ALLOWED_PREVIEW:
        raise ValidationError(f"{label} has unsupported previewPolicy: {payload['previewPolicy']}")
    if 'provenance' in payload and not isinstance(payload['provenance'], dict):
        raise ValidationError(f"{label} has invalid provenance")
    if 'identityConfidence' in payload and payload['identityConfidence'] not in _ALLOWED_CONFIDENCE:
        raise ValidationError(f"{label} has unsupported identityConfidence: {payload['identityConfidence']}")


def validate_release(release: dict[str, Any]) -> None:
    if release.get("schema_version") != 1:
        raise ValidationError("Unsupported release schema")
    if not release.get("release_id"):
        raise ValidationError("Release is missing release_id")
    if not release.get("rows"):
        raise ValidationError("Release has no rows")

    for row in release["rows"]:
        if not row.get("id"):
            raise ValidationError("Row is missing id")
        if not isinstance(row.get("items"), list):
            raise ValidationError(f"Row {row['id']} has no item array")
        _validate_home_contract(row, f"Row {row['id']}")
        for item in row['items']:
            _validate_home_contract(item, f"Item in row {row['id']}")