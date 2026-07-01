"""Project directory and artefact path management (TD 7).

Layout::

    projects/<project_slug>/
      project.yaml
      cut_index.json
      eagle_dry_run.json
      eagle_apply_result.json
      exports/
        review.html
        cut_index.json
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


def exports_dir(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    """Return ``projects/<slug>/exports/`` (M5 / M5-early HTML report output)."""
    return project_dir(slug, base_dir) / "exports"


def review_html_path(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return exports_dir(slug, base_dir) / "review.html"


def exported_cut_index_path(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    """Return ``projects/<slug>/exports/cut_index.json`` (M5 immutable snapshot)."""
    return exports_dir(slug, base_dir) / "cut_index.json"


def eagle_dry_run_path(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return project_dir(slug, base_dir) / "eagle_dry_run.json"


def eagle_apply_result_path(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return project_dir(slug, base_dir) / "eagle_apply_result.json"


def eagle_mapping_default_template_path() -> Path:
    """Return the packaged default Eagle mapping template path.

    ``<package_root>/templates/eagle_mapping.default.yaml``
    """
    return Path(__file__).parent / "templates" / "eagle_mapping.default.yaml"


def cache_dir(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return project_dir(slug, base_dir) / "cache"


def thumbnails_dir(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return cache_dir(slug, base_dir) / "thumbnails"


def frames_dir(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return cache_dir(slug, base_dir) / "frames"


def transcripts_dir(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    return cache_dir(slug, base_dir) / "transcripts"


def logs_dir(slug: str, base_dir: Optional[_PathLike] = None) -> Path:
    """Return ``projects/<slug>/logs/`` (M3 / Q24 structured JSONL logs)."""
    return project_dir(slug, base_dir) / "logs"


def analyze_log_path(slug: str, ts: str, base_dir: Optional[_PathLike] = None) -> Path:
    """Return the JSONL log file path for an analyze/run invocation.

    ``ts`` is a compact ISO 8601 timestamp (e.g. ``20260625T140000Z``); the
    caller is responsible for producing one. Layout::

        projects/<slug>/logs/analyze-<ts>.jsonl
    """
    return logs_dir(slug, base_dir) / f"analyze-{ts}.jsonl"


def cluster_log_path(slug: str, ts: str, base_dir: Optional[_PathLike] = None) -> Path:
    """Return the JSONL log file path for a cluster invocation.

    ``ts`` is a compact ISO 8601 timestamp (e.g. ``20260625T140000Z``); the
    caller is responsible for producing one. Layout::

        projects/<slug>/logs/cluster-<ts>.jsonl
    """
    return logs_dir(slug, base_dir) / f"cluster-{ts}.jsonl"


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
    "exports_dir",
    "review_html_path",
    "exported_cut_index_path",
    "eagle_dry_run_path",
    "eagle_apply_result_path",
    "eagle_mapping_default_template_path",
    "cache_dir",
    "thumbnails_dir",
    "frames_dir",
    "transcripts_dir",
    "logs_dir",
    "analyze_log_path",
    "cluster_log_path",
    "ensure_project_dirs",
]
