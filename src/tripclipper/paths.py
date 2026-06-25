"""Project directory and artefact path management (TD 7).

Layout::

    projects/<project_slug>/
      project.yaml
      cut_index.json
      assets.csv
      segments.csv
      summary.md
      review.html
      eagle_dry_run.json
      eagle_apply_result.json
      cache/
        thumbnails/
        frames/
        transcripts/

The project root defaults to ``<cwd>/projects`` but a ``base_dir`` may be
supplied (e.g. a tmp dir in tests).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

_PathLike = Union[str, Path]


def _root(base_dir: Optional[_PathLike]) -> Path:
    """Resolve the project root directory."""
    if base_dir is None:
        return Path.cwd() / "projects"
    return Path(base_dir)


def project_dir(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return _root(base_dir) / slug


def cut_index_path(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return project_dir(slug, base_dir) / "cut_index.json"


def project_config_path(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return project_dir(slug, base_dir) / "project.yaml"


def assets_csv_path(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return project_dir(slug, base_dir) / "assets.csv"


def segments_csv_path(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return project_dir(slug, base_dir) / "segments.csv"


def summary_md_path(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return project_dir(slug, base_dir) / "summary.md"


def review_html_path(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return project_dir(slug, base_dir) / "review.html"


def eagle_dry_run_path(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return project_dir(slug, base_dir) / "eagle_dry_run.json"


def eagle_apply_result_path(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return project_dir(slug, base_dir) / "eagle_apply_result.json"


def cache_dir(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return project_dir(slug, base_dir) / "cache"


def thumbnails_dir(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return cache_dir(slug, base_dir) / "thumbnails"


def frames_dir(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return cache_dir(slug, base_dir) / "frames"


def transcripts_dir(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return cache_dir(slug, base_dir) / "transcripts"


def ensure_project_dirs(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    """Idempotently create the project directory and cache sub-directories.

    Creates ``project_dir`` and ``cache/{thumbnails,frames,transcripts}``.
    Repeated calls do not error and do not clear existing files. Returns the
    project directory path.
    """
    pdir = project_dir(slug, base_dir)
    for directory in (
        thumbnails_dir(slug, base_dir),
        frames_dir(slug, base_dir),
        transcripts_dir(slug, base_dir),
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return pdir


__all__ = [
    "project_dir",
    "cut_index_path",
    "project_config_path",
    "assets_csv_path",
    "segments_csv_path",
    "summary_md_path",
    "review_html_path",
    "eagle_dry_run_path",
    "eagle_apply_result_path",
    "cache_dir",
    "thumbnails_dir",
    "frames_dir",
    "transcripts_dir",
    "ensure_project_dirs",
]
