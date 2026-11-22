"""Static publication with slim rows and one rich detail file per item."""
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from .validate import validate_release

MAX_PUBLISHED_JSON_BYTES = 4 * 1024 * 1024
SHARD_INLINE_TARGET_BYTES = 3 * 1024 * 1024
SHARD_MARKER = "__viewsync_shard_v1__"


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


def _detail_filename(detail_document: dict) -> str:
    canonical = json.dumps(
        detail_document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{hashlib.sha256(canonical).hexdigest()}.json"


def _write_shard_part(root: Path, payload, written: set[str]) -> str:
    envelope = {"schema_version": 1, "payload": payload}
    encoded = _encode_json(envelope)
    if len(encoded) > MAX_PUBLISHED_JSON_BYTES:
        raise ValueError("Internal detail shard exceeded the published JSON limit")
    digest = hashlib.sha256(encoded).hexdigest()
    relative = f"details/parts/{digest}.json"
    write_json(root / relative, envelope)
    written.add(relative)
    return relative


def _shard_detail_value(value, root: Path, written: set[str]):
    """Recursively split a large JSON value into lossless, content-addressed parts."""
    if len(_encode_json(value)) <= SHARD_INLINE_TARGET_BYTES:
        return value

    if isinstance(value, str):
        # Build UTF-8-safe chunks in linear time. Re-encoding an ever-growing
        # candidate string for every character is quadratic and punishes long
        # credits/review/translation strings.
        chunks: list[str] = []
        current: list[str] = []
        current_bytes = 2  # JSON string quotes
        for character in value:
            character_bytes = len(
                json.dumps(character, ensure_ascii=False).encode("utf-8")
            )
            if current and current_bytes + character_bytes > SHARD_INLINE_TARGET_BYTES:
                chunks.append("".join(current))
                current = []
                current_bytes = 2
            current.append(character)
            current_bytes += character_bytes
        if current or not chunks:
            chunks.append("".join(current))
        paths = [_write_shard_part(root, chunk, written) for chunk in chunks]
        return {SHARD_MARKER: {"kind": "string", "parts": paths}}

    if isinstance(value, dict):
        parts: list[str] = []
        current: dict = {}
        current_bytes = 2  # opening and closing braces
        for key, child in value.items():
            sharded_child = _shard_detail_value(child, root, written)
            key_bytes = len(_encode_json(str(key)))
            child_encoded = _encode_json(sharded_child)
            # Account for the extra indentation introduced when this value is
            # nested beneath its enclosing object in the pretty-printed file.
            child_bytes = len(child_encoded) + 2 * child_encoded.count(b"\\n")
            entry_bytes = key_bytes + 2 + child_bytes + 8
            comma_bytes = 1 if current else 0
            if current and current_bytes + comma_bytes + entry_bytes > SHARD_INLINE_TARGET_BYTES:
                parts.append(_write_shard_part(root, current, written))
                current = {}
                current_bytes = 2
                comma_bytes = 0
            current[key] = sharded_child
            current_bytes += comma_bytes + entry_bytes
            if current_bytes > MAX_PUBLISHED_JSON_BYTES:
                raise ValueError(
                    f"Unable to shard detail object field {key!r} without data loss"
                )
        if current or not parts:
            parts.append(_write_shard_part(root, current, written))
        return {SHARD_MARKER: {"kind": "map", "parts": parts}}

    if isinstance(value, list):
        parts: list[str] = []
        current: list = []
        current_bytes = 2  # opening and closing brackets
        for child in value:
            sharded_child = _shard_detail_value(child, root, written)
            child_encoded = _encode_json(sharded_child)
            child_bytes = len(child_encoded) + 2 * child_encoded.count(b"\\n") + 8
            comma_bytes = 1 if current else 0
            if current and current_bytes + comma_bytes + child_bytes > SHARD_INLINE_TARGET_BYTES:
                parts.append(_write_shard_part(root, current, written))
                current = []
                current_bytes = 2
                comma_bytes = 0
            current.append(sharded_child)
            current_bytes += comma_bytes + child_bytes
            if current_bytes > MAX_PUBLISHED_JSON_BYTES:
                raise ValueError("Unable to shard detail array without data loss")
        if current or not parts:
            parts.append(_write_shard_part(root, current, written))
        return {SHARD_MARKER: {"kind": "list", "parts": parts}}

    # Numbers, booleans and null values are always small. Reaching this branch
    # means a future non-JSON type was supplied to the publisher.
    raise ValueError(f"Unsupported oversized detail value: {type(value).__name__}")


def _write_detail_document(
    root: Path,
    relative_path: str,
    detail_document: dict,
    written_shards: set[str],
):
    expected = f"details/{_detail_filename(detail_document)}"
    if relative_path != expected:
        raise ValueError(f"Detail path is not content-addressed: {relative_path}")
    target = root / relative_path
    encoded = _encode_json(detail_document)
    if len(encoded) <= MAX_PUBLISHED_JSON_BYTES:
        return write_json(target, detail_document)
    sharded = _shard_detail_value(detail_document, root, written_shards)
    # The root remains a small stable pointer to the losslessly sharded tree.
    return write_json(
        target,
        {
            SHARD_MARKER: {
                "kind": "root",
                "payload": sharded,
            }
        },
    )


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
        "discovery_quality",
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

    # Detail content is shared by every row/shelf that references it. Stable
    # content-addressed paths let unchanged documents survive new releases
    # without being written under a fresh release-specific directory.
    published_details = set()
    written_shards: set[str] = set()
    for relative_path, details in item_details.items():
        safe_path = _safe_relative_path(relative_path)
        if (
            len(safe_path.parts) != 2
            or safe_path.parts[0] != "details"
            or safe_path.suffix != ".json"
        ):
            raise ValueError(f"Detail path is outside the content-addressed detail prefix: {relative_path}")
        detail_id = details.get("id") if isinstance(details, dict) else None
        if not detail_id:
            raise ValueError(f"Detail document is missing its canonical ID: {relative_path}")
        _write_detail_document(
            root,
            relative_path,
            details,
            written_shards,
        )
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
