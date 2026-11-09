"""Persistent source snapshots, retention policy, and last-good release state."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fetch import SourceSnapshot, load_snapshot, save_snapshot


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def snapshot_age_hours(snapshot: SourceSnapshot, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - parse_timestamp(snapshot.fetched_at)).total_seconds() / 3600)


def retention_status(age_hours: float, policy: dict[str, Any]) -> str:
    if age_hours <= float(policy.get("fresh_hours", 12)):
        return "fresh"
    if age_hours <= float(policy.get("full_retention_hours", 48)):
        return "retained_full"
    if age_hours <= float(policy.get("declining_retention_hours", 96)):
        return "retained_declining"
    return "expired"


def snapshot_status(
    snapshot: SourceSnapshot,
    policy: dict[str, Any],
    now: datetime | None = None,
) -> str:
    return retention_status(snapshot_age_hours(snapshot, now), policy)


def select_snapshots(
    snapshots: list[SourceSnapshot],
    policy: dict[str, Any],
    now: datetime | None = None,
) -> tuple[list[SourceSnapshot], list[SourceSnapshot]]:
    """Split snapshots into usable and expired groups using the retention policy."""

    usable: list[SourceSnapshot] = []
    expired: list[SourceSnapshot] = []

    for snapshot in snapshots:
        if snapshot_status(snapshot, policy, now) == "expired":
            expired.append(snapshot)
        else:
            usable.append(snapshot)

    return usable, expired


def restore_snapshots(state_dir: str | Path) -> dict[str, SourceSnapshot]:
    snapshot_dir = Path(state_dir) / "source-snapshots"
    snapshots: dict[str, SourceSnapshot] = {}

    if not snapshot_dir.exists():
        return snapshots

    for path in snapshot_dir.glob("*.json"):
        try:
            snapshot = load_snapshot(path)
            snapshots[snapshot.request_id] = snapshot
        except (OSError, ValueError, TypeError, KeyError):
            continue

    return snapshots


def persist_snapshots(snapshots: list[SourceSnapshot], state_dir: str | Path) -> None:
    snapshot_dir = Path(state_dir) / "source-snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    for snapshot in snapshots:
        save_snapshot(snapshot, snapshot_dir)


def preserve_last_good_release(state_dir: str | Path, output_dir: str | Path) -> bool:
    marker = Path(state_dir) / "last-good-release" / "release.json"
    if not marker.exists():
        return False

    with open(marker, "r", encoding="utf-8") as handle:
        release = json.load(handle)

    release_id = release.get("release_id")
    if not release_id:
        return False

    source = Path(output_dir) / "v1" / "releases" / release_id
    if not source.exists():
        return False

    target = Path(output_dir) / "v1" / "releases" / f"{release_id}-preserved"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return True
