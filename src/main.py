"""Viewsync catalogue generation entry point."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_config
from .fetch import SourceSnapshot, fetch_source, utc_now
from .http_client import FetchError
from .identity import media_identity
from .merge_metadata import merge_item
from .publish import publish_release
from .rank import build_ranking, order_items
from .state import persist_snapshots, restore_snapshots, retention_status, snapshot_age_hours
from .validate import has_usable_items, validate_snapshot


def generate(config_dir: str, output_dir: str, state_dir: str) -> int:
    config = load_config(config_dir)
    output = Path(output_dir)
    state = Path(state_dir)

    previous = restore_snapshots(state)
    fresh_snapshots: list[SourceSnapshot] = []
    failures: list[str] = []

    for provider in config["sources"].get("providers", []):
        if not provider.get("enabled"):
            continue

        for request in provider.get("requests", []):
            try:
                snapshot = fetch_source(request, provider)
                validate_snapshot(snapshot)
                if not has_usable_items(snapshot):
                    raise FetchError(f"Source {request['id']} returned no usable items")
                fresh_snapshots.append(snapshot)
                print(
                    f"Fetched {request['id']}: {len(snapshot.items)} items",
                    flush=True,
                )
            except (FetchError, ValueError) as error:
                message = f"{request['id']}: {type(error).__name__}: {error}"
                failures.append(message)
                print(f"Source failure: {message}", file=sys.stderr, flush=True)

    snapshots_by_request = {snapshot.request_id: snapshot for snapshot in fresh_snapshots}
    snapshots_by_request.update(previous)

    policy = config["ranking"].get("freshness", {})
    eligible: list[SourceSnapshot] = []
    now = datetime.now(timezone.utc)

    for snapshot in snapshots_by_request.values():
        age = snapshot_age_hours(snapshot, now)
        status = retention_status(age, policy)
        if status != "expired":
            eligible.append(snapshot)

    if not eligible:
        print("No eligible source snapshots; cannot generate a new release.", file=sys.stderr)
        print("Failures:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    release_id = uuid.uuid4().hex
    rows: list[dict[str, Any]] = []

    for row_config in config["rows"].get("rows", []):
        row_snapshots = [
            snapshot
            for snapshot in eligible
            if snapshot.list_id in row_config["source_lists"]
            and snapshot.media_type == row_config["media_type"]
        ]

        if not row_snapshots:
            print(f"No eligible snapshots for row {row_config['id']}", file=sys.stderr)
            continue

        items_by_id: dict[str, dict[str, Any]] = {}

        for snapshot in row_snapshots:
            for meta in snapshot.items:
                identity = media_identity(snapshot.media_type, meta)
                media_id = identity["id"]
                enriched = dict(meta)
                enriched["_viewsync_id"] = media_id

                items_by_id[media_id] = merge_item(
                    snapshot.media_type,
                    items_by_id.get(media_id),
                    enriched,
                    snapshot.provider_id,
                )

        rankings = build_ranking(
            row_snapshots,
            k=int(config["ranking"].get("k", 60)),
            provider_weights=config["ranking"].get("provider_weights", {}),
        )

        ordered = order_items(list(items_by_id.values()), rankings)
        max_items = int(row_config.get("max_items", 100))
        date_field = row_config.get("date_field")

        if date_field:
            ordered = [
                item for item in ordered
                if item.get(date_field)
            ]
            ordered.sort(key=lambda item: item[date_field])

        published_items = []
        for position, item in enumerate(ordered[:max_items], start=1):
            media_id = item["_viewsync_id"]
            entry = rankings.get(media_id, {})
            published_items.append({
                "id": media_id,
                "type": item["type"],
                "title": item.get("title"),
                "year": item.get("year"),
                "poster": item.get("poster"),
                "backdrop": item.get("backdrop"),
                "overview": item.get("overview"),
                "rating": item.get("rating"),
                "release_date": item.get("release_date"),
                "field_sources": item.get("field_sources", {}),
                "ranking": {
                    "position": position,
                    "consensus_score": entry.get("consensus_score", 0.0),
                    "source_count": entry.get("source_count", 0),
                    "source_ranks": entry.get("source_ranks", {}),
                    "best_rank": entry.get("best_rank"),
                    "average_rank": entry.get("average_rank"),
                },
            })

        contributing = len({snapshot.provider_id for snapshot in row_snapshots})
        configured = len(row_config["source_lists"])
        status = "fresh" if contributing == configured else "reduced_coverage"

        rows.append({
            "id": row_config["id"],
            "title": row_config["title"],
            "media_type": row_config["media_type"],
            "data_updated_at": utc_now(),
            "status": status,
            "configured_provider_count": configured,
            "contributing_provider_count": contributing,
            "items": published_items,
        })

    if not rows:
        print("No rows could be generated.", file=sys.stderr)
        print("Failures:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    release = {
        "schema_version": 1,
        "release_id": release_id,
        "published_at": utc_now(),
        "ranking_version": "rrf-v1",
        "rows": rows,
    }

    manifest_path = publish_release(release, output)
    persist_snapshots(fresh_snapshots, state)

    state_dir = Path(state) / "last-good-release"
    state_dir.mkdir(parents=True, exist_ok=True)
    with open(state_dir / "release.json", "w", encoding="utf-8") as handle:
        json.dump({"release_id": release_id}, handle)

    print(f"Published release {release_id}: {manifest_path}")
    if failures:
        print("Source failures:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the Viewsync catalogue")
    parser.add_argument("--config", default="catalog-config")
    parser.add_argument("--output", default="dist")
    parser.add_argument("--state", default="state")
    args = parser.parse_args()

    return generate(args.config, args.output, args.state)


if __name__ == "__main__":
    raise SystemExit(main())
