"""Tests for installing existing Jianying draft content into a Jianying 10 shell."""

from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path

import pytest

from tripclipper.jianying import (
    DraftInstallError,
    DraftInstallRequest,
    InstallValidationItem,
    Jianying10Installer,
    bundled_template_dir,
)
from tripclipper.jianying.paths import resolve_media_path, template_timeline_dir

ROOT = Path(__file__).resolve().parents[1]
JIANYING_FIXTURES = ROOT / "tests" / "fixtures" / "jianying"
REALISTIC_DRAFT = JIANYING_FIXTURES / "realistic_draft_content.json"
MINIMAL_TEMPLATE = JIANYING_FIXTURES / "minimal_template_draft"
DEMO_DRAFTS = [
    ROOT / "projects" / "demo-scan" / "exports" / "draft_content.json",
    ROOT / "projects" / "demo-scan" / "exports" / "draft_content_swap_video_2_3.json",
]


def _copy_draft_content(tmp_path: Path, source: Path = REALISTIC_DRAFT) -> Path:
    target = tmp_path / "input" / "draft_content.json"
    target.parent.mkdir(parents=True)
    shutil.copy2(source, target)
    return target


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _install(
    tmp_path: Path,
    *,
    draft_content_path: Path | None = None,
    template_draft_dir: Path | None = None,
    draft_name: str = "Summer Trip",
) -> tuple[Path, object]:
    drafts_dir = tmp_path / "jianying-drafts"
    request = DraftInstallRequest(
        draft_content_path=draft_content_path or _copy_draft_content(tmp_path),
        draft_name=draft_name,
        jianying_drafts_dir=drafts_dir,
        template_draft_dir=template_draft_dir,
    )
    result = Jianying10Installer().install(request)
    return drafts_dir, result


def test_public_installer_symbols_are_exported() -> None:
    assert DraftInstallRequest
    assert InstallValidationItem
    assert DraftInstallError
    assert Jianying10Installer
    assert bundled_template_dir().is_dir()


def test_preflight_rejects_missing_draft_content_before_creating_destination(tmp_path: Path) -> None:
    drafts_dir = tmp_path / "drafts"

    with pytest.raises(DraftInstallError, match="draft_content_path"):
        Jianying10Installer().install(
            DraftInstallRequest(
                draft_content_path=tmp_path / "missing.json",
                draft_name="Broken",
                jianying_drafts_dir=drafts_dir,
            )
        )

    assert not drafts_dir.exists()


def test_preflight_rejects_invalid_template_override_before_creating_destination(tmp_path: Path) -> None:
    draft_content = _copy_draft_content(tmp_path)
    drafts_dir = tmp_path / "drafts"

    with pytest.raises(DraftInstallError, match="template_draft_dir"):
        Jianying10Installer().install(
            DraftInstallRequest(
                draft_content_path=draft_content,
                draft_name="Broken",
                jianying_drafts_dir=drafts_dir,
                template_draft_dir=tmp_path / "missing-template",
            )
        )

    assert not drafts_dir.exists()


def test_preflight_rejects_missing_default_drafts_dir_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft_content = _copy_draft_content(tmp_path)
    monkeypatch.delenv("TRIPCLIPPER_JIANYING_DRAFTS_DIR", raising=False)
    monkeypatch.setattr("tripclipper.jianying.paths.DEFAULT_DRAFTS_DIR_CANDIDATES", ())

    with pytest.raises(DraftInstallError, match="jianying_drafts_dir"):
        Jianying10Installer().install(
            DraftInstallRequest(draft_content_path=draft_content, draft_name="Needs Discovery")
        )


def test_preflight_rejects_invalid_explicit_drafts_dir_before_creating_destination(tmp_path: Path) -> None:
    draft_content = _copy_draft_content(tmp_path)
    drafts_file = tmp_path / "not-a-directory"
    drafts_file.write_text("nope", encoding="utf-8")

    with pytest.raises(DraftInstallError, match="jianying_drafts_dir"):
        Jianying10Installer().install(
            DraftInstallRequest(
                draft_content_path=draft_content,
                draft_name="Broken",
                jianying_drafts_dir=drafts_file,
            )
        )


def test_preflight_rejects_unreadable_media_and_writes_failure_report(tmp_path: Path) -> None:
    payload = _load_json(REALISTIC_DRAFT)
    payload["materials"]["videos"][0]["path"] = str(tmp_path / "missing-video.mp4")
    draft_content = tmp_path / "input" / "draft_content.json"
    _write_json(draft_content, payload)
    drafts_dir = tmp_path / "drafts"

    with pytest.raises(DraftInstallError, match="media"):
        Jianying10Installer().install(
            DraftInstallRequest(
                draft_content_path=draft_content,
                draft_name="Broken Media",
                jianying_drafts_dir=drafts_dir,
            )
        )

    assert not drafts_dir.exists()
    report = _load_json(draft_content.parent / "install_report.json")
    assert report["status"] == "failure"
    assert "missing-video.mp4" in json.dumps(report, ensure_ascii=False)


def test_successful_install_uses_bundled_template_and_explicit_destination(tmp_path: Path) -> None:
    drafts_dir, result = _install(tmp_path)
    expected_timeline_id = template_timeline_dir(bundled_template_dir()).name

    assert result.draft_dir.parent == drafts_dir
    assert result.draft_dir.name == "tc-summer-trip"
    assert result.draft_dir.is_dir()
    assert result.timeline_id == expected_timeline_id
    assert result.report_path == tmp_path / "input" / "install_report.json"
    assert result.report_path.is_file()
    assert _load_json(result.report_path)["status"] == "success"


def test_bundled_template_install_fills_renderable_template_slots(tmp_path: Path) -> None:
    payload = _load_json(REALISTIC_DRAFT)
    payload["metadata_path"] = "tests/fixtures/media/should-not-be-rewritten.mp4"
    draft_content = tmp_path / "input" / "draft_content.json"
    _write_json(draft_content, payload)

    _, result = _install(tmp_path, draft_content_path=draft_content)
    installed = _load_json(result.draft_dir / "draft_content.json")
    template = _load_json(bundled_template_dir() / "draft_content.json")

    assert [(track["type"], len(track["segments"])) for track in installed["tracks"]] == [
        (track["type"], len(track["segments"])) for track in template["tracks"]
    ]
    assert [item["id"] for item in installed["materials"]["videos"]] == [
        item["id"] for item in template["materials"]["videos"]
    ]

    video_items = installed["materials"]["videos"]
    audio_items = installed["materials"]["audios"]
    for item in video_items + audio_items:
        media_path = Path(item["path"])
        assert media_path.is_file()
        assert item["remote_url"] == item["path"]

    assert all(
        Path(item["path"]).parent == result.draft_dir / "assets" / "video"
        for item in video_items
        if item["type"] == "video"
    )
    assert all(
        Path(item["path"]).parent == result.draft_dir / "assets" / "image"
        for item in video_items
        if item["type"] == "photo"
    )
    assert all(Path(item["path"]).parent == result.draft_dir / "assets" / "audio" for item in audio_items)
    assert "metadata_path" not in installed


def test_swap_input_fills_template_main_video_slots_from_timeline_order(tmp_path: Path) -> None:
    _, original = _install(
        tmp_path / "original",
        draft_content_path=DEMO_DRAFTS[0],
        draft_name="Original",
    )
    _, swapped = _install(
        tmp_path / "swapped",
        draft_content_path=DEMO_DRAFTS[1],
        draft_name="Swapped",
    )

    original_installed = _load_json(original.draft_dir / "draft_content.json")
    swapped_installed = _load_json(swapped.draft_dir / "draft_content.json")

    def main_video_slot_paths(payload: dict, draft_dir: Path) -> list[Path]:
        video_by_id = {
            item["id"]: Path(item["path"])
            for item in payload["materials"]["videos"]
            if item["type"] == "video"
        }
        main_track = next(
            track for track in payload["tracks"]
            if track["type"] == "video" and len(track["segments"]) == 8
        )
        return [video_by_id[segment["material_id"]] for segment in main_track["segments"]]

    original_slots = main_video_slot_paths(original_installed, original.draft_dir)
    swapped_slots = main_video_slot_paths(swapped_installed, swapped.draft_dir)
    source_payload = _load_json(DEMO_DRAFTS[0])
    source_by_id = {item["id"]: item for item in source_payload["materials"]["videos"]}
    source_segments = next(
        track for track in source_payload["tracks"]
        if track["type"] == "video" and len(track["segments"]) == 8
    )["segments"]
    source_paths = [
        resolve_media_path(
            source_by_id[segment["material_id"]]["path"],
            draft_content_path=DEMO_DRAFTS[0],
        )
        for segment in source_segments
    ]

    assert all(path is not None for path in source_paths)
    assert _sha256(original_slots[1]) == _sha256(source_paths[1])
    assert _sha256(original_slots[2]) == _sha256(source_paths[2])
    assert _sha256(swapped_slots[1]) == _sha256(source_paths[2])
    assert _sha256(swapped_slots[2]) == _sha256(source_paths[1])


def test_draft_content_files_are_written_consistently(tmp_path: Path) -> None:
    _, result = _install(tmp_path)
    timeline_dir = result.draft_dir / "Timelines" / result.timeline_id
    required = [
        result.draft_dir / "draft_content.json",
        result.draft_dir / "draft_content.json.bak",
        timeline_dir / "draft_content.json",
        timeline_dir / "draft_content.json.bak",
    ]

    payloads = [_load_json(path) for path in required]

    assert all(path.is_file() for path in required)
    assert all(payload == payloads[0] for payload in payloads)
    assert payloads[0]["id"] == result.timeline_id


def test_jianying_template_tmp_files_preserve_shell_metadata(tmp_path: Path) -> None:
    _, result = _install(tmp_path)
    timeline_dir = result.draft_dir / "Timelines" / result.timeline_id
    template = bundled_template_dir()
    template_timeline_dir = next(path for path in (template / "Timelines").iterdir() if path.is_dir())

    assert (result.draft_dir / "template.tmp").read_bytes() == (template / "template.tmp").read_bytes()
    assert (result.draft_dir / "template-2.tmp").read_bytes() == (
        result.draft_dir / "draft_info.json"
    ).read_bytes()
    assert (timeline_dir / "template.tmp").read_bytes() == (
        template_timeline_dir / "template.tmp"
    ).read_bytes()
    assert (timeline_dir / "template-2.tmp").read_bytes() == (
        timeline_dir / "draft_info.json"
    ).read_bytes()


def test_structured_metadata_is_updated_when_template_files_are_parseable(tmp_path: Path) -> None:
    _, result = _install(tmp_path, template_draft_dir=MINIMAL_TEMPLATE, draft_name="Metadata Check")

    project = _load_json(result.draft_dir / "project.json")
    layout = _load_json(result.draft_dir / "timeline_layout.json")
    meta = _load_json(result.draft_dir / "draft_meta_info.json")

    assert project["timeline_id"] == result.timeline_id
    assert project["name"] == "Metadata Check"
    assert project["draft_fold_path"] == str(result.draft_dir)
    assert layout["timeline_id"] == result.timeline_id
    assert meta["draft_name"] == "Metadata Check"
    assert meta["draft_timeline_id"] == result.timeline_id
    assert meta["draft_fold_path"] == str(result.draft_dir)


def test_timeline_project_metadata_is_updated_for_bundled_template(tmp_path: Path) -> None:
    _, result = _install(tmp_path, draft_name="Bundled Metadata")

    project = _load_json(result.draft_dir / "Timelines" / "project.json")
    project_backup = _load_json(result.draft_dir / "Timelines" / "project.json.bak")
    layout = _load_json(result.draft_dir / "timeline_layout.json")

    for payload in (project, project_backup):
        assert payload["id"] == result.timeline_id
        assert payload["main_timeline_id"] == result.timeline_id
        assert payload["timelines"][0]["id"] == result.timeline_id
        assert payload["timelines"][0]["name"] == "Bundled Metadata"
    assert layout["activeTimeline"] == result.timeline_id
    assert layout["dockItems"][0]["timelineIds"] == [result.timeline_id]
    assert layout["dockItems"][0]["timelineNames"] == ["Bundled Metadata"]


def test_post_creation_failure_removes_incomplete_draft_and_writes_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft_content = _copy_draft_content(tmp_path)
    drafts_dir = tmp_path / "drafts"

    def fail_media_copy(src: Path, dst: Path) -> Path:
        raise OSError("copy boom")

    monkeypatch.setattr("tripclipper.jianying.installer.shutil.copy2", fail_media_copy)

    with pytest.raises(DraftInstallError, match="copy boom"):
        Jianying10Installer().install(
            DraftInstallRequest(
                draft_content_path=draft_content,
                draft_name="Rollback",
                jianying_drafts_dir=drafts_dir,
            )
        )

    assert not list(drafts_dir.iterdir())
    report = _load_json(draft_content.parent / "install_report.json")
    assert report["status"] == "failure"
    assert "copy boom" in report["message"]


def test_repeated_installs_reuse_template_timeline_and_generate_unique_draft_directories(
    tmp_path: Path,
) -> None:
    draft_content = _copy_draft_content(tmp_path)
    drafts_dir = tmp_path / "drafts"
    installer = Jianying10Installer()
    expected_timeline_id = template_timeline_dir(bundled_template_dir()).name
    request = DraftInstallRequest(
        draft_content_path=draft_content,
        draft_name="Repeat Me",
        jianying_drafts_dir=drafts_dir,
    )

    first = installer.install(request)
    second = installer.install(request)

    assert first.timeline_id == expected_timeline_id
    assert second.timeline_id == expected_timeline_id
    assert first.draft_dir != second.draft_dir
    assert first.draft_dir.name == "tc-repeat-me"
    assert second.draft_dir.name == "tc-repeat-me-2"


def test_default_drafts_dir_discovery_can_use_environment_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft_content = _copy_draft_content(tmp_path)
    discovered = tmp_path / "discovered-drafts"
    discovered.mkdir()
    monkeypatch.setenv("TRIPCLIPPER_JIANYING_DRAFTS_DIR", str(discovered))

    result = Jianying10Installer().install(
        DraftInstallRequest(draft_content_path=draft_content, draft_name="Discovered")
    )

    assert result.draft_dir.parent == discovered


def test_bundled_template_is_sanitized() -> None:
    template = bundled_template_dir()
    forbidden_names = {"backup", "cache", ".DS_Store", "assets"}
    all_paths = list(template.rglob("*"))

    assert template.is_dir()
    assert not any(path.name in forbidden_names for path in all_paths)
    for path in all_paths:
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            assert "/Users/" not in text
            assert "C:\\" not in text


def test_opaque_json_metadata_files_are_preserved_without_parsing(tmp_path: Path) -> None:
    template = bundled_template_dir()
    original_meta = (template / "draft_meta_info.json").read_bytes()
    original_info = (template / "draft_info.json").read_bytes()

    _, result = _install(tmp_path)

    assert (result.draft_dir / "draft_meta_info.json").read_bytes() == original_meta
    assert (result.draft_dir / "draft_info.json").read_bytes() == original_info


@pytest.mark.parametrize("demo_draft", DEMO_DRAFTS)
def test_demo_scan_draft_content_inputs_install_for_manual_comparison(
    tmp_path: Path,
    demo_draft: Path,
) -> None:
    draft_content = _copy_draft_content(tmp_path, source=demo_draft)
    drafts_dir = tmp_path / "drafts"

    result = Jianying10Installer().install(
        DraftInstallRequest(
            draft_content_path=draft_content,
            draft_name=f"Demo {demo_draft.stem}",
            jianying_drafts_dir=drafts_dir,
        )
    )

    installed = _load_json(result.draft_dir / "draft_content.json")
    copied_paths = [Path(item["path"]) for item in installed["materials"]["videos"]]
    copied_paths.extend(Path(item["path"]) for item in installed["materials"]["audios"])
    assert copied_paths
    assert all(path.is_file() and result.draft_dir / "assets" in path.parents for path in copied_paths)
    assert all(
        Path(item["path"]).parent == result.draft_dir / "assets" / "video"
        for item in installed["materials"]["videos"]
        if item["type"] == "video"
    )
    assert all(
        Path(item["path"]).parent == result.draft_dir / "assets" / "image"
        for item in installed["materials"]["videos"]
        if item["type"] == "photo"
    )
    assert all(
        Path(item["path"]).parent == result.draft_dir / "assets" / "audio"
        for item in installed["materials"]["audios"]
    )
