from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from misco_harness.distribution import DistributionError, materialize_source, upgrade_workspace
from misco_harness.workspace import new_workspace


PROJECT_ROOT = Path(__file__).parents[2]
PROFILE_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "misco_profile"


def _copy_harness_source(destination: Path, *, marker: str | None = None) -> Path:
    destination.mkdir(parents=True)
    for relative in (
        "src",
        "contracts",
        "pyproject.toml",
        "uv.lock",
        "WORK_RESEARCH_COORDINATOR.md",
        "harness.manifest.json",
    ):
        source = PROJECT_ROOT / relative
        target = destination / relative
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    if marker is not None:
        (destination / "WORK_RESEARCH_COORDINATOR.md").write_text(marker, encoding="utf-8")
    return destination


def _new_workspace(tmp_path: Path, *, source: Path | None = None, profile: Path | None = None) -> Path:
    theme = tmp_path / "theme.md"
    expectations = tmp_path / "expectations.md"
    theme.write_text("theme", encoding="utf-8")
    expectations.write_text("expectations", encoding="utf-8")
    target = tmp_path / "research"
    new_workspace(
        target,
        template_root=source or PROJECT_ROOT,
        theme=theme,
        expectations=expectations,
        worker_backend="mock",
        profile_source=profile,
    )
    return target


def test_new_installs_profile_lock_and_explicit_git_init(tmp_path: Path) -> None:
    target = tmp_path / "research"
    theme = tmp_path / "theme.md"
    expectations = tmp_path / "expectations.md"
    theme.write_text("theme", encoding="utf-8")
    expectations.write_text("expectations", encoding="utf-8")

    new_workspace(
        target,
        template_root=PROJECT_ROOT,
        theme=theme,
        expectations=expectations,
        worker_backend="mock",
        profile_source=PROFILE_FIXTURE,
        profile_ref="v0.1.0",
        init_git=True,
    )

    lock = json.loads((target / "harness.lock.json").read_text(encoding="utf-8"))
    assert lock["profile"]["profile_id"] == "misco"
    assert (target / "maps" / "misco-profile-map.md").is_file()
    assert (target / ".git" / "HEAD").is_file()
    assert not list((target / ".git" / "refs" / "heads").glob("*"))
    assert (target / "intake" / "drop" / ".gitkeep").is_file()
    state = json.loads((target / ".rh" / "state" / "orchestrator" / "head.json").read_text(encoding="utf-8"))
    assert state["active_attention_map_id"] is None


def test_upgrade_replaces_harness_and_preserves_research_runtime(tmp_path: Path) -> None:
    target = _new_workspace(tmp_path, profile=PROFILE_FIXTURE)
    before_state = (target / ".rh" / "state" / "research" / "head.json").read_bytes()
    source_v2 = _copy_harness_source(tmp_path / "harness-v2", marker="updated coordinator\n")

    result = upgrade_workspace(
        target,
        harness_source=source_v2,
        harness_ref="v0.2.0",
    )

    assert result["status"] == "UPGRADED"
    assert (target / "WORK_RESEARCH_COORDINATOR.md").read_text(encoding="utf-8") == "updated coordinator\n"
    assert (target / ".rh" / "state" / "research" / "head.json").read_bytes() == before_state
    lock = json.loads((target / "harness.lock.json").read_text(encoding="utf-8"))
    assert lock["harness"]["ref"] == "v0.2.0"
    assert list((target / ".rh" / "lifecycle" / "upgrades").glob("upgrade-*.json"))


def test_upgrade_refuses_modified_managed_file_without_mutation(tmp_path: Path) -> None:
    target = _new_workspace(tmp_path)
    managed = target / "WORK_RESEARCH_COORDINATOR.md"
    original = managed.read_bytes()
    managed.write_text("research-side edit\n", encoding="utf-8")
    source_v2 = _copy_harness_source(tmp_path / "harness-v2", marker="updated\n")

    with pytest.raises(DistributionError, match="modified outside Harness"):
        upgrade_workspace(target, harness_source=source_v2, harness_ref="v0.2.0")

    assert managed.read_text(encoding="utf-8") == "research-side edit\n"
    assert not list((target / ".rh" / "lifecycle" / "upgrades").glob("upgrade-*.json"))
    assert original != managed.read_bytes()


def test_profile_only_upgrade_keeps_harness_revision(tmp_path: Path) -> None:
    target = _new_workspace(tmp_path, profile=PROFILE_FIXTURE)
    profile_v2 = shutil.copytree(PROFILE_FIXTURE, tmp_path / "profile-v2")
    feedback = profile_v2 / "project_feedback" / "misco-profile-feedback.md"
    feedback.write_text("profile v2\n", encoding="utf-8")
    before_harness = json.loads((target / "harness.lock.json").read_text(encoding="utf-8"))["harness"]

    result = upgrade_workspace(
        target,
        harness_source=None,
        harness_ref=None,
        profile_source=profile_v2,
        profile_ref="v0.1.1",
    )

    assert result["status"] == "UPGRADED"
    assert feedback.read_text(encoding="utf-8") == "profile v2\n"
    assert (target / "project_feedback" / "misco-profile-feedback.md").read_text(encoding="utf-8") == "profile v2\n"
    after_harness = json.loads((target / "harness.lock.json").read_text(encoding="utf-8"))["harness"]
    assert after_harness == before_harness


def test_upgrade_refuses_pending_work_without_mutation(tmp_path: Path) -> None:
    target = _new_workspace(tmp_path)
    state_path = target / ".rh" / "state" / "orchestrator" / "head.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["pending_work"] = {"run_id": "run-pending"}
    state_path.write_text(json.dumps(state), encoding="utf-8")
    source_v2 = _copy_harness_source(tmp_path / "harness-v2", marker="updated\n")

    with pytest.raises(DistributionError, match="pending Work"):
        upgrade_workspace(target, harness_source=source_v2, harness_ref="v0.2.0")

    assert (target / "WORK_RESEARCH_COORDINATOR.md").read_text(encoding="utf-8") != "updated\n"


def test_archive_extraction_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.txt", "must not extract")

    with pytest.raises(DistributionError, match="escapes"):
        with materialize_source(archive, ref="v0.1.0", manifest_name="harness.manifest.json"):
            pass


def test_archive_extraction_rejects_git_content(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe-git.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(".git/config", "must not extract")

    with pytest.raises(DistributionError, match=r"\.git"):
        with materialize_source(archive, ref="v0.1.0", manifest_name="harness.manifest.json"):
            pass
