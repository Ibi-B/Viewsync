"""Validate and persist the allow-listed durable Viewsync state tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

ALLOWED_ROOT_FILES = {".gitkeep", "generation-report.json"}
ALLOWED_ROOT_DIRS = {"source-snapshots", "last-good-release"}
SNAPSHOT_DIR = "source-snapshots"
LAST_GOOD_PATH = PurePosixPath("last-good-release/release.json")


class StateSafetyError(ValueError):
    """Raised when the checked-out state tree violates the state contract."""


def _regular_file(path: Path, *, allow_git_metadata: bool = False) -> None:
    if path.is_symlink():
        raise StateSafetyError(f"Symlink is not allowed: {path.name}")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise StateSafetyError(f"Not a regular file: {path.name}")
    if stat.S_IMODE(info.st_mode) & 0o111:
        raise StateSafetyError(f"Executable file is not allowed: {path.name}")


def _json_file(path: Path, *, tolerate_malformed: bool = False) -> str | None:
    _regular_file(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if tolerate_malformed:
            return f"Unreadable snapshot retained for restore quarantine: {path.name} ({type(exc).__name__})"
        raise StateSafetyError(f"Invalid JSON state file: {path.name}") from exc
    if not isinstance(payload, dict):
        if tolerate_malformed:
            return f"Snapshot is not a JSON object and will be quarantined during restore: {path.name}"
        raise StateSafetyError(f"State JSON must be an object: {path.name}")
    return None


def _data_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if entry.name == ".git":
            if entry.is_symlink() or not (entry.is_dir() or entry.is_file()):
                raise StateSafetyError("Checkout Git metadata is not a regular path")
            if entry.is_file():
                _regular_file(entry, allow_git_metadata=True)
            continue
        if entry.name in ALLOWED_ROOT_FILES:
            if entry.name == ".gitkeep":
                _regular_file(entry)
            else:
                _json_file(entry)
                files.append(entry)
            continue
        if entry.name not in ALLOWED_ROOT_DIRS:
            raise StateSafetyError(f"Unexpected state path: {entry.name}")
        if entry.is_symlink() or not entry.is_dir():
            raise StateSafetyError(f"State directory is not a real directory: {entry.name}")
        if entry.name == SNAPSHOT_DIR:
            for child in sorted(entry.iterdir(), key=lambda item: item.name):
                if child.is_symlink() or not child.is_file() or child.suffix != ".json":
                    raise StateSafetyError(f"Unexpected snapshot entry: {child.name}")
                warning = _json_file(child, tolerate_malformed=True)
                if warning:
                    print(warning)
                files.append(child)
        else:
            for child in sorted(entry.iterdir(), key=lambda item: item.name):
                if child.name != "release.json":
                    raise StateSafetyError(f"Unexpected last-good state entry: {child.name}")
                _json_file(child)
                files.append(child)
    return files


def validate_state_dir(state_dir: str | Path, secrets: tuple[str, ...] = ()) -> list[str]:
    root = Path(state_dir)
    if root.is_symlink() or not root.is_dir():
        raise StateSafetyError("State root must be an existing, real directory")
    files = _data_files(root)
    warnings: list[str] = []
    for path in files:
        raw = path.read_bytes()
        for secret in secrets:
            if secret and secret.encode("utf-8") in raw:
                raise StateSafetyError(f"Credential material detected in state file: {path.name}")
        if path.parent.name == SNAPSHOT_DIR:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                warnings.append(path.name)
                continue
            if not isinstance(payload, dict):
                warnings.append(path.name)
    return warnings


def _snapshot_hashes(state_dir: Path) -> dict[str, str]:
    directory = state_dir / SNAPSHOT_DIR
    if not directory.exists():
        return {}
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir(), key=lambda item: item.name)
        if path.is_file() and path.suffix == ".json" and not path.is_symlink()
    }


def capture_baseline(state_dir: str | Path, baseline_path: str | Path, secrets: tuple[str, ...] = ()) -> None:
    root = Path(state_dir)
    validate_state_dir(root, secrets=secrets)
    target = Path(baseline_path)
    if target.is_symlink() or target.resolve().is_relative_to(root.resolve()):
        raise StateSafetyError("Snapshot baseline must be outside the durable state tree")
    target.parent.mkdir(parents=True, exist_ok=True)
    required_paths = sorted(path.relative_to(root).as_posix() for path in _data_files(root))
    payload = {
        "snapshot_sha256": _snapshot_hashes(root),
        "required_paths": required_paths,
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)


def verify_append_only(state_dir: str | Path, baseline_path: str | Path, secrets: tuple[str, ...] = ()) -> None:
    root = Path(state_dir)
    validate_state_dir(root, secrets=secrets)
    baseline_file = Path(baseline_path)
    _regular_file(baseline_file)
    baseline: Any = json.loads(baseline_file.read_text(encoding="utf-8"))
    previous = baseline.get("snapshot_sha256") if isinstance(baseline, dict) else None
    required_paths = baseline.get("required_paths") if isinstance(baseline, dict) else None
    if not isinstance(previous, dict) or not isinstance(required_paths, list):
        raise StateSafetyError("Snapshot baseline is malformed")
    for name in required_paths:
        if not isinstance(name, str):
            raise StateSafetyError("Snapshot baseline contains an invalid path")
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise StateSafetyError("Snapshot baseline contains an unsafe path")
        existing = root.joinpath(*relative.parts)
        if existing.is_symlink() or not existing.is_file():
            raise StateSafetyError(f"Existing state file was deleted: {name}")
    current = _snapshot_hashes(root)
    for filename, digest in previous.items():
        if filename not in current:
            raise StateSafetyError(f"Existing snapshot was deleted: {filename}")
        if current[filename] != digest:
            raise StateSafetyError(f"Existing snapshot was modified: {filename}")


def verify_staged_paths(state_dir: str | Path) -> None:
    root = Path(state_dir)
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-only", "-z"],
        check=True,
        capture_output=True,
    )
    changed = [name.decode("utf-8") for name in result.stdout.split(b"\0") if name]
    for name in changed:
        path = PurePosixPath(name)
        allowed = (
            name in ALLOWED_ROOT_FILES
            or name == str(LAST_GOOD_PATH)
            or (path.parent == PurePosixPath(SNAPSHOT_DIR) and path.suffix == ".json")
        )
        if not allowed:
            raise StateSafetyError(f"Refusing to commit unexpected state path: {name}")


def _secrets_from_environment() -> tuple[str, ...]:
    return tuple(
        value
        for name in ("TMDB_API_KEY", "TMDB_ACCESS_TOKEN", "TRAKT_CLIENT_ID")
        if (value := os.environ.get(name))
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and protect durable Viewsync state")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--state-dir", required=True, type=Path)
    capture = commands.add_parser("capture")
    capture.add_argument("--state-dir", required=True, type=Path)
    capture.add_argument("--baseline", required=True, type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("--state-dir", required=True, type=Path)
    verify.add_argument("--baseline", required=True, type=Path)
    staged = commands.add_parser("verify-staged")
    staged.add_argument("--state-dir", required=True, type=Path)
    args = parser.parse_args()
    secrets = _secrets_from_environment()

    if args.command == "validate":
        warnings = validate_state_dir(args.state_dir, secrets=secrets)
        print(f"State tree valid; {len(warnings)} malformed snapshot(s) retained for restore reporting.")
    elif args.command == "capture":
        capture_baseline(args.state_dir, args.baseline, secrets=secrets)
        print("Append-only snapshot baseline captured.")
    elif args.command == "verify":
        verify_append_only(args.state_dir, args.baseline, secrets=secrets)
        print("State tree valid; existing snapshots are unchanged and retained.")
    elif args.command == "verify-staged":
        verify_staged_paths(args.state_dir)
        print("Staged state paths match the allow-list.")


if __name__ == "__main__":
    main()
