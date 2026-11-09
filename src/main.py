"""Viewsync catalogue generation entry point."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_config
from .fetch import SourceSnapshot, fetch_source
from .manifest import build_release
from .publish import publish_release
from .state import persist_snapshots, preserve_last_good_release, select_snapshots
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


def _fetch_snapshots(
    config_dir: Path,
    now: datetime,
) -> tuple[list[SourceSnapshot], list[dict[str, str]]]:
    requests = load_json(config_dir / "requests.json")
    snapshots: list[SourceSnapshot] = []
    failures: list[dict[str, str]] = []

    for request in requests:
        request_id = str(request.get("id") or "")
        if not request_id:
            continue

        for provider_id, provider_config in request.get("providers", {}).items():
            try:
                items = fetch_source(request, provider_id, now.date())
            except Exception as exc:
                failures.append(
                    {
                        "request_id": request_id,
                        "provider_id": provider_id,
                        "error": str(exc),
                    }
                )
                continue

            snapshots.append(
                SourceSnapshot(
                    request_id=request_id,
                    provider_id=provider_id,
                    list_id=str(provider_config.get("list_id") or request_id),
                    media_type=str(provider_config.get("media_type") or ""),
                    fetched_at=now.isoformat(),
                    items=items,
                )
            )

    return snapshots, failures


def _write_generation_report(
    output_dir: Path,
    now: datetime,
    usable_count: int,
    expired: list[SourceSnapshot],
    failures: list[dict[str, str]],
) -> None:
    report = {
        "generated_at": now.isoformat(),
        "snapshot_count": usable_count + len(expired),
        "usable_snapshot_count": usable_count,
        "expired_snapshot_count": len(expired),
        "fetch_failure_count": len(failures),
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
    write_json(output_dir / "state" / "generation-report.json", report)


def _manifest_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate_catalog(
    config_dir: str | Path = CONFIG,
    output_dir: str | Path = OUTPUT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Generate, validate, publish, and point to the current catalogue release."""

    now = now or datetime.now(timezone.utc)
    config_dir = Path(config_dir)
    output_dir = Path(output_dir)
    state_dir = output_dir / "state"

    config = load_config(config_dir)
    snapshots, failures = _fetch_snapshots(config_dir, now)

    if not snapshots:
        _write_generation_report(output_dir, now, 0, [], failures)
        raise ValueError("No provider snapshots were available; refusing to publish a release")

    policy = config["ranking"].get("retention", {})
    provider_weights = config["ranking"].get("provider_weights", {})
    usable_snapshots, expired_snapshots = select_snapshots(snapshots, policy, now)

    _write_generation_report(
        output_dir,
        now,
        len(usable_snapshots),
        expired_snapshots,
        failures,
    )

    if not usable_snapshots:
        raise ValueError("All provider snapshots have expired; refusing to publish a new release")

    persist_snapshots(usable_snapshots, state_dir)
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

    return release


def main() -> None:
    generate_catalog()


if __name__ == "__main__":
    main()
