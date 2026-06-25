"""Tests for project directory management."""

from __future__ import annotations

from pathlib import Path

from tripclipper.paths import (
    cut_index_path,
    ensure_project_dirs,
    frames_dir,
    project_dir,
    thumbnails_dir,
    transcripts_dir,
)


def test_ensure_project_dirs_creates_cache_subdirs(tmp_path: Path) -> None:
    slug = "demo-project"
    returned = ensure_project_dirs(slug, base_dir=tmp_path)

    assert returned == project_dir(slug, base_dir=tmp_path)
    assert returned.is_dir()
    assert thumbnails_dir(slug, base_dir=tmp_path).is_dir()
    assert frames_dir(slug, base_dir=tmp_path).is_dir()
    assert transcripts_dir(slug, base_dir=tmp_path).is_dir()


def test_ensure_project_dirs_idempotent_preserves_files(tmp_path: Path) -> None:
    slug = "demo-project"
    ensure_project_dirs(slug, base_dir=tmp_path)

    # Drop a file into the project dir and a cache subdir.
    sentinel = cut_index_path(slug, base_dir=tmp_path)
    sentinel.write_text("{}", encoding="utf-8")
    thumb = thumbnails_dir(slug, base_dir=tmp_path) / "keep.txt"
    thumb.write_text("keep", encoding="utf-8")

    # Second call must not error or clear existing content.
    ensure_project_dirs(slug, base_dir=tmp_path)

    assert sentinel.is_file()
    assert sentinel.read_text(encoding="utf-8") == "{}"
    assert thumb.is_file()
    assert thumb.read_text(encoding="utf-8") == "keep"


def test_standard_paths_are_under_project_dir(tmp_path: Path) -> None:
    slug = "demo"
    pdir = project_dir(slug, base_dir=tmp_path)
    assert cut_index_path(slug, base_dir=tmp_path) == pdir / "cut_index.json"
