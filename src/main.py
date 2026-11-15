"""Viewsync catalogue generation entry point."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_config
from .fetch import SourceSnapshot, fetch_source
from .manifest import build_release
from .publish import publish_release
from .state import (
    persist_snapshots,
    preserve_last_good_release,
    restore_snapshots,
    select_snapshots,
)
from .validate import validate_release

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / "catalog-config"
OUTPUT = BASE / "dist"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _safe_fetch_error(exc: Exception) -> str:
    """Keep diagnostic context while preventing credentials entering durable reports."""
    message = str(exc)
    for name in ("TMDB_API_KEY", "TMDB_ACCESS_TOKEN", "TRAKT_CLIENT_ID"):
        secret = os.environ.get(name)
        if secret:
            message = message.replace(secret, "[REDACTED]")
    message = re.sub(
        r"(?i)([?&](?:api_key|access_token|token|client_secret)=)[^&\\s]+",
        lambda match: match.group(1) + "[REDACTED]",
        message,
    )
    return message[:2000]


def _fetch_snapshots(
    config_dir: Path,
    now: datetime,
    state_dir: Path,
) -> tuple[list[SourceSnapshot], list[dict[str, Any]], list[dict[str, str]]]:
    """Fetch current data and retain the last valid snapshot for failed sources."""
    requests = load_json(config_dir / "requests.json")
    restore_errors: list[dict[str, str]] = []
    restored = restore_snapshots(state_dir, errors=restore_errors)
    snapshots: dict[str, SourceSnapshot] = dict(restored)
    failures: list[dict[str, Any]] = []

    for request in requests:
        request_id = str(request.get("id") or "")
        if not request_id:
            continue

        for provider_id, provider_config in request.get("providers", {}).items():
            raw_payloads: list[Any] = []
            try:
                items = fetch_source(request, provider_id, now.date(), raw_responses=raw_payloads)
            except Exception as exc:
                failures.append(
                    {
                        "request_id": request_id,
                        "provider_id": provider_id,
                        "error": _safe_fetch_error(exc),
                        "partial_response_count": len(raw_payloads),
                        "partial_raw_payloads": raw_payloads,
                    }
                )
                continue

            snapshot = SourceSnapshot(
                request_id=request_id,
                provider_id=provider_id,
                list_id=str(provider_config.get("list_id") or request_id),
                media_type=str(provider_config.get("media_type") or ""),
                fetched_at=now.isoformat(),
                items=items,
                raw_payloads=raw_payloads,
            )
            snapshot_key = f"{request_id}:{provider_id}:{snapshot.list_id}"
            snapshots[snapshot_key] = snapshot

    return list(snapshots.values()), failures, restore_errors


def _write_generation_report(
    state_dir: Path,
    now: datetime,
    usable_count: int,
    expired: list[SourceSnapshot],
    failures: list[dict[str, Any]],
    restore_errors: list[dict[str, str]],
    snapshots: list[SourceSnapshot],
) -> None:
    report = {
        "generated_at": now.isoformat(),
        "snapshot_count": usable_count + len(expired),
        "usable_snapshot_count": usable_count,
        "expired_snapshot_count": len(expired),
        "fetch_failure_count": len(failures),
        "restore_error_count": len(restore_errors),
        "empty_snapshot_count": sum(not snapshot.items for snapshot in snapshots),
        "snapshot_inventory": [
            {
                "request_id": snapshot.request_id,
                "provider_id": snapshot.provider_id,
                "list_id": snapshot.list_id,
                "fetched_at": snapshot.fetched_at,
                "item_count": len(snapshot.items),
            }
            for snapshot in snapshots
        ],
        "restore_errors": restore_errors,
        "expired_snapshots": [
            {
                "request_id": snapshot.request_id,
                "provider_id": snapshot.provider_id,
                "list_id": snapshot.list_id,
                "fetched_at": snapshot.fetched_at,
            }
            for snapshot in expired
        ],
        "fetch_failures": failures,
    }
    write_json(state_dir / "generation-report.json", report)


def _manifest_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate_catalog(
    config_dir: str | Path = CONFIG,
    output_dir: str | Path = OUTPUT,
    now: datetime | None = None,
    state_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Generate, validate, publish, and point to the current catalogue release."""

    now = now or datetime.now(timezone.utc)
    config_dir = Path(config_dir)
    output_dir = Path(output_dir)
    state_dir = Path(state_dir) if state_dir is not None else output_dir / "state"

    config = load_config(config_dir)
    snapshots, failures, restore_errors = _fetch_snapshots(config_dir, now, state_dir)

    if not snapshots:
        _write_generation_report(state_dir, now, 0, [], failures, restore_errors, snapshots)
        raise ValueError(
            "No current or retained provider snapshots were available; refusing to publish"
        )

    # ranking.json defines the retention tiers under "retention". Keep this
    # policy shared by snapshot selection and release freshness reporting.
    policy = config["ranking"].get("retention", {})
    provider_weights = config["ranking"].get("provider_weights", {})
    usable_snapshots, expired_snapshots = select_snapshots(snapshots, policy, now)

    _write_generation_report(
        state_dir,
        now,
        len(usable_snapshots),
        expired_snapshots,
        failures,
        restore_errors,
        snapshots,
    )

    # Preserve every gathered/restored source payload, not only snapshots used
    # in this release. Retention controls publication eligibility, not storage.
    persist_snapshots(snapshots, state_dir)

    if not usable_snapshots:
        raise ValueError("All provider snapshots have expired; refusing to publish a new release")

    preserve_last_good_release(state_dir, output_dir)

    release = build_release(
        config["rows"]["rows"],
        usable_snapshots,
        now,
        retention_policy=policy,
        provider_weights=provider_weights,
    )

    if not release["rows"]:
        raise ValueError("No catalogue rows could be generated from available snapshots")

    validate_release(release)
    publish_release(release, output_dir)

    manifest_path = output_dir / "v1" / "manifest.json"
    current = {
        "schema_version": 2,
        "release_id": release["release_id"],
        "manifest_path": "v1/manifest.json",
        "manifest_sha256": _manifest_hash(manifest_path),
        "generated_at": release["generated_at"],
        "ranking_version": release["ranking_version"],
        "catalog_freshness": release["catalog_freshness"],
        "status": "current",
    }

    current_path = output_dir / "v1" / "current.json"
    write_json(current_path, current)

    verified = json.loads(current_path.read_text(encoding="utf-8"))
    if verified["release_id"] != release["release_id"]:
        raise ValueError("Current-release pointer does not match the published release")
    if verified["manifest_sha256"] != _manifest_hash(manifest_path):
        raise ValueError("Current-release pointer hash does not match the published manifest")

    # Advance the last-good marker only after the release and pointer have both
    # passed validation. A failed generation therefore cannot replace it.
    write_json(
        state_dir / "last-good-release" / "release.json",
        {
            "release_id": release["release_id"],
            "manifest_sha256": verified["manifest_sha256"],
            "generated_at": release["generated_at"],
        },
    )

    return release


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Viewsync catalogue")
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--state", type=Path, default=None)
    args = parser.parse_args()
    generate_catalog(args.config, args.output, state_dir=args.state)


if __name__ == "__main__":
    main()
