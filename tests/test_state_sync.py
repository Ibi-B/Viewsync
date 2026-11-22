import json
from pathlib import Path

import pytest

from src.state import restore_snapshots
from src.state_sync import (
    StateSafetyError,
    capture_baseline,
    validate_state_dir,
    verify_append_only,
    verify_staged_paths,
)


def _snapshot(request_id="popular_movies", item_id=1):
    return {
        "request_id": request_id,
        "provider_id": "tmdb",
        "list_id": request_id,
        "media_type": "movie",
        "fetched_at": "2026-11-15T00:00:00+00:00",
        "items": [{"id": item_id}],
        "raw_payloads": [{"results": [{"id": item_id}]}],
    }


def _write_snapshot(state_dir: Path, name="snapshot.json", payload=None):
    directory = state_dir / "source-snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(payload if payload is not None else _snapshot()), encoding="utf-8")
    return path


def test_empty_state_checkout_and_git_metadata_are_allowed(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / ".git").mkdir()
    (state / ".gitkeep").write_text("initial state branch\n", encoding="utf-8")

    assert validate_state_dir(state) == []


def test_snapshot_additions_are_allowed_but_existing_snapshots_are_immutable(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    first = _write_snapshot(state, "first.json", _snapshot(item_id=1))
    baseline = tmp_path / "baseline.json"

    capture_baseline(state, baseline)
    _write_snapshot(state, "second.json", _snapshot(request_id="new_movies", item_id=2))
    (state / "generation-report.json").write_text(json.dumps({"fetch_failures": []}), encoding="utf-8")
    last_good = state / "last-good-release"
    last_good.mkdir()
    (last_good / "release.json").write_text(json.dumps({"release_id": "r1"}), encoding="utf-8")

    verify_append_only(state, baseline)

    first.write_text(json.dumps(_snapshot(item_id=99)), encoding="utf-8")
    with pytest.raises(StateSafetyError, match="modified"):
        verify_append_only(state, baseline)


def test_snapshot_deletion_is_rejected(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    snapshot = _write_snapshot(state)
    baseline = tmp_path / "baseline.json"
    capture_baseline(state, baseline)
    snapshot.unlink()

    with pytest.raises(StateSafetyError, match="deleted"):
        verify_append_only(state, baseline)


def test_malformed_snapshot_is_retained_and_reported_by_restore(tmp_path):
    state = tmp_path / "state"
    snapshot_dir = state / "source-snapshots"
    snapshot_dir.mkdir(parents=True)
    malformed = snapshot_dir / "broken.json"
    malformed.write_text("{not-json", encoding="utf-8")

    warnings = validate_state_dir(state)
    errors = []
    restored = restore_snapshots(state, errors=errors)

    assert warnings == ["broken.json"]
    assert restored == {}
    assert errors and errors[0]["file"] == "broken.json"
    assert malformed.exists()
    assert malformed.read_text(encoding="utf-8") == "{not-json"


def test_symlinks_are_rejected_without_following_them(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_snapshot()), encoding="utf-8")
    (state / "source-snapshots").mkdir()
    try:
        (state / "source-snapshots" / "linked.json").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable in this environment")

    with pytest.raises(StateSafetyError, match="Unexpected snapshot entry"):
        validate_state_dir(state)


def test_executable_and_unexpected_files_are_rejected(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    unexpected = state / "run.sh"
    unexpected.write_text("echo unsafe", encoding="utf-8")
    with pytest.raises(StateSafetyError, match="Unexpected state path"):
        validate_state_dir(state)

    unexpected.unlink()
    executable = _write_snapshot(state)
    executable.chmod(0o755)
    with pytest.raises(StateSafetyError, match="Executable file"):
        validate_state_dir(state)


def test_credentials_in_state_are_rejected(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "generation-report.json").write_text(
        json.dumps({"debug": "example-secret-token"}), encoding="utf-8"
    )

    with pytest.raises(StateSafetyError, match="Credential material"):
        validate_state_dir(state, secrets=("example-secret-token",))


def test_baseline_must_be_outside_state_tree(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    with pytest.raises(StateSafetyError, match="outside"):
        capture_baseline(state, state / "baseline.json")


def test_existing_generation_report_cannot_be_deleted(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    report = state / "generation-report.json"
    report.write_text(json.dumps({"runs": 1}), encoding="utf-8")
    baseline = tmp_path / "baseline.json"

    capture_baseline(state, baseline)
    report.unlink()

    with pytest.raises(StateSafetyError, match="generation-report.json"):
        verify_append_only(state, baseline)


def test_existing_last_good_marker_cannot_be_deleted(tmp_path):
    state = tmp_path / "state"
    marker = state / "last-good-release" / "release.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"release_id": "r1"}), encoding="utf-8")
    baseline = tmp_path / "baseline.json"

    capture_baseline(state, baseline)
    marker.unlink()

    with pytest.raises(StateSafetyError, match="last-good-release/release.json"):
        verify_append_only(state, baseline)


def test_staged_paths_reject_files_outside_the_state_contract(tmp_path):
    import subprocess

    state = tmp_path / "state"
    state.mkdir()
    subprocess.run(["git", "init", str(state)], check=True, capture_output=True)
    unexpected = state / "credentials.txt"
    unexpected.write_text("must-not-be-committed", encoding="utf-8")
    subprocess.run(["git", "-C", str(state), "add", "--all"], check=True, capture_output=True)

    with pytest.raises(StateSafetyError, match="unexpected state path"):
        verify_staged_paths(state)


def test_production_workflow_is_manual_only_and_scopes_write_permissions():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "generate-catalogue.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "schedule:" in workflow
    assert '- cron: "17 */6 * * *"' in workflow
    assert workflow.count("contents: write") == 1
    assert "state-sync:" in workflow
    assert "if: github.ref == 'refs/heads/main' || github.event_name == 'pull_request'" in workflow
    assert workflow.count("uses: actions/checkout@v4") == 2
    assert "ref: viewsync-state" in workflow
    assert "path: state" in workflow
    assert "python -m src.main --config catalog-config --output dist --state state" in workflow
    assert "uses: actions/upload-pages-artifact@v3" in workflow
    assert "path: dist" in workflow
    assert "group: viewsync-state" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "git push --force" not in workflow
    assert "git -C state push origin HEAD:refs/heads/viewsync-state" in workflow


def test_test_only_workflow_never_checks_out_or_writes_durable_state():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "test-only.yml").read_text(encoding="utf-8")

    assert "contents: write" not in workflow
    assert "viewsync-state" not in workflow
    assert "secrets." not in workflow
    assert "uses: actions/checkout@v4" in workflow
    assert ("ref: " + "$" + "{{ github.sha }}") in workflow
    assert "if: github.ref == 'refs/heads/main'" in workflow
    assert workflow.count("python -m pytest") == 2
    assert "src.main" not in workflow
    assert "upload-pages-artifact" not in workflow
    assert "deploy-pages" not in workflow
