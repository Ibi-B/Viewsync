"""Static publication with slim rows and one rich detail file per item."""
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from .validate import validate_release

MAX_PUBLISHED_JSON_BYTES = 4 * 1024 * 1024


def _encode_json(data) -> bytes:
    return (
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def write_json(path, data, *, max_bytes=MAX_PUBLISHED_JSON_BYTES):
    path = Path(path)
    encoded = _encode_json(data)
    if len(encoded) > max_bytes:
        raise ValueError(
            f"Published JSON document {path.name} is {len(encoded)} bytes; "
            f"limit is {max_bytes} bytes"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)
    return path


def safe_component(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError(f"Unsafe publication identifier: {value!r}")
    return value


def _detail_filename(media_id: str) -> str:
    digest = hashlib.sha256(media_id.encode("utf-8")).hexdigest()[:24]
    return f"{digest}.json"


def _safe_relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"Unsafe publication path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe publication path: {value!r}")
    return path


def _slim_row_item(source: dict):
    allowed = (
        "id",
        "media_kind",
        "title",
        "year",
        "ids",
        "release_date",
        "images",
        "metadata",
        "details_path",
        "popularity",
        "vote_count",
        "source_attribution",
        "ranking",
    )
    item = {key: source[key] for key in allowed if key in source}
    if not item.get("details_path"):
        raise ValueError(f"Catalogue row item {item.get('id')!r} has no details_path")
    return item


def _slim_shelf_item(source: dict):
    allowed = (
        "id",
        "tmdb_id",
        "media_kind",
        "title",
        "year",
        "release_date",
        "images",
        "popularity",
        "rating",
        "vote_count",
        "rank",
        "details_path",
        "ids",
    )
    item = {key: source[key] for key in allowed if key in source}
    if not item.get("details_path"):
        raise ValueError(f"Provider shelf item {item.get('id')!r} has no details_path")
    return item


def publish_release(release, output_dir):
    validate_release(release)
    root = Path(output_dir) / "v1"
    release_id = safe_component(release["release_id"])
    directory = root / "releases" / release_id
    item_details = release.get("item_details") or {}
    provider_shelves = release.get("provider_shelves") or []

    # Publish each full media record exactly once, shared by all global rows and
    # regional provider shelves. These documents are replaced with each release.
    published_details = set()
    for relative_path, details in item_details.items():
        safe_path = _safe_relative_path(relative_path)
        expected_prefix = PurePosixPath("releases") / release_id / "items"
        if safe_path.parts[:3] != expected_prefix.parts or safe_path.suffix != ".json":
            raise ValueError(f"Detail path is outside the release item prefix: {relative_path}")
        detail_id = details.get("id") if isinstance(details, dict) else None
        if not detail_id:
            raise ValueError(f"Detail document is missing its canonical ID: {relative_path}")
        expected_name = _detail_filename(str(detail_id))
        if safe_path.name != expected_name:
            raise ValueError(f"Detail path does not match canonical ID: {relative_path}")
        write_json(root / Path(*safe_path.parts), details)
        published_details.add(relative_path)

    manifest = {
        key: release[key]
        for key in (
            "schema_version",
            "release_id",
            "generated_at",
            "ranking_version",
            "catalog_freshness",
        )
    }
    manifest["watch_regions"] = release.get("watch_regions", [])
    manifest.update(
        path_base="v1-root",
        manifest_path=f"releases/{release_id}/manifest.json",
        rows=[],
    )

    targets = []
    referenced_details = set()

    for row in release["rows"]:
        row_id = safe_component(row["id"])
        row_path = directory / "rows" / f"{row_id}.json"
        entry = {
            key: row[key]
            for key in (
                "id",
                "title",
                "media_kind",
                "data_updated_at",
                "status",
                "configured_provider_count",
                "contributing_provider_count",
            )
            if key in row
        }
        entry["path"] = row_path.relative_to(root).as_posix()
        manifest["rows"].append(entry)

        items = []
        for source in row["items"]:
            item = _slim_row_item(source)
            safe_path = _safe_relative_path(item["details_path"])
            if item["details_path"] not in published_details:
                raise ValueError(
                    f"Row references an unpublished detail document: {item['details_path']}"
                )
            referenced_details.add(item["details_path"])
            items.append(item)

        payload = {
            key: row[key]
            for key in (
                "id",
                "title",
                "media_type",
                "media_kind",
                "data_updated_at",
                "status",
            )
            if key in row
        }
        payload.update(
            schema_version=2,
            release_id=release_id,
            path_base="v1-root",
            items=items,
        )
        write_json(row_path, payload)
        targets.append(row_path)

    for regional in provider_shelves:
        region = safe_component(str(regional.get("region") or "").upper())
        region_record = next(
            (item for item in manifest["watch_regions"] if item.get("iso_code") == region),
            None,
        )
        if region_record is None:
            raise ValueError(f"Provider shelves published for undeclared region {region}")
        relative_path = region_record.get("provider_shelves_path")
        safe_path = _safe_relative_path(relative_path or "")
        expected = PurePosixPath("releases") / release_id / "provider-shelves"
        if safe_path.parts[:3] != expected.parts or safe_path.suffix != ".json":
            raise ValueError(f"Provider shelf path is outside release prefix: {relative_path}")

        shelves = []
        for source_shelf in regional.get("shelves", []):
            shelf = {
                key: value for key, value in source_shelf.items() if key != "items"
            }
            shelf["items"] = []
            for source_item in source_shelf.get("items", []):
                item = _slim_shelf_item(source_item)
                if item["details_path"] not in published_details:
                    raise ValueError(
                        f"Provider shelf references an unpublished detail document: {item['details_path']}"
                    )
                referenced_details.add(item["details_path"])
                shelf["items"].append(item)
            shelves.append(shelf)

        payload = {
            "schema_version": 2,
            "release_id": release_id,
            "region": region,
            "shelves": shelves,
        }
        target = root / Path(*safe_path.parts)
        write_json(target, payload)
        targets.append(target)

    missing_references = referenced_details - published_details
    if missing_references:
        raise ValueError(f"Unpublished detail references: {sorted(missing_references)[:5]}")

    release_manifest = directory / "manifest.json"
    write_json(release_manifest, manifest)
    targets.append(release_manifest)

    for target in targets:
        json.loads(target.read_text(encoding="utf-8"))

    return write_json(root / "manifest.json", manifest)


def publication_size_report(output_dir):
    """Measure the current static release without reading metadata into memory."""
    root = Path(output_dir) / "v1"
    if not root.exists():
        return {
            "json_file_count": 0,
            "total_bytes": 0,
            "maximum_file_bytes": 0,
            "maximum_file": None,
            "files_over_limit": [],
            "limit_bytes": MAX_PUBLISHED_JSON_BYTES,
        }

    files = sorted(root.rglob("*.json"))
    sizes = [(path, path.stat().st_size) for path in files]
    maximum = max(sizes, key=lambda pair: pair[1], default=(None, 0))
    return {
        "json_file_count": len(sizes),
        "total_bytes": sum(size for _, size in sizes),
        "maximum_file_bytes": maximum[1],
        "maximum_file": (
            maximum[0].relative_to(root).as_posix() if maximum[0] else None
        ),
        "files_over_limit": [
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": size,
            }
            for path, size in sizes
            if size > MAX_PUBLISHED_JSON_BYTES
        ],
        "limit_bytes": MAX_PUBLISHED_JSON_BYTES,
    }
