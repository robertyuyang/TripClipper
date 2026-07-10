"""Path helpers for Jianying draft installation."""

from __future__ import annotations

import os
import re
import secrets
import unicodedata
from importlib import resources
from pathlib import Path

DEFAULT_DRAFTS_DIR_CANDIDATES: tuple[Path, ...] = (
    Path.home() / "Movies" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft",
    Path.home() / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
    Path.home() / "Documents" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft",
    Path.home() / "Documents" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
)


def slugify_draft_name(name: str) -> str:
    """Return an ASCII slug suitable for TripClipper-created draft directories."""
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.lower()).strip("-")
    return slug or "draft"


def unique_draft_dir(parent: Path, draft_name: str) -> Path:
    """Build a unique ``tc-...`` draft directory path under ``parent``."""
    slug = slugify_draft_name(draft_name)
    candidate = parent / f"tc-{slug}"
    if not candidate.exists():
        return candidate

    for counter in range(2, 1000):
        candidate = parent / f"tc-{slug}-{counter}"
        if not candidate.exists():
            return candidate

    for _ in range(100):
        candidate = parent / f"tc-{slug}-{secrets.token_hex(2)}"
        if not candidate.exists():
            return candidate

    raise RuntimeError("Unable to generate a unique Jianying draft directory name")


def bundled_template_dir() -> Path:
    """Return the bundled Jianying 10 template shell directory."""
    return Path(str(resources.files("tripclipper.jianying") / "templates" / "jianying10_template"))


def install_report_path(draft_content_path: Path) -> Path:
    """Return the install report path beside the source draft content."""
    return draft_content_path.parent / "install_report.json"


def discover_jianying_drafts_dir() -> Path | None:
    """Discover one clear local Jianying drafts directory, if available."""
    env_path = os.environ.get("TRIPCLIPPER_JIANYING_DRAFTS_DIR")
    if env_path:
        candidate = Path(env_path).expanduser()
        return candidate if candidate.is_dir() else None

    candidates = [path.expanduser() for path in DEFAULT_DRAFTS_DIR_CANDIDATES if path.expanduser().is_dir()]
    if len(candidates) == 1:
        return candidates[0]
    return None


def template_timeline_dir(template_draft_dir: Path) -> Path:
    """Find the reusable template timeline directory inside a Jianying draft shell."""
    timelines_dir = template_draft_dir / "Timelines"
    if not timelines_dir.is_dir():
        raise FileNotFoundError(f"template_draft_dir is missing Timelines/: {template_draft_dir}")

    candidates = [
        path
        for path in sorted(timelines_dir.iterdir())
        if path.is_dir()
        and (path / "draft_content.json").is_file()
        and (path / "draft_content.json.bak").is_file()
        and (path / "template.tmp").is_file()
        and (path / "template-2.tmp").is_file()
    ]
    if not candidates:
        raise FileNotFoundError(
            "template_draft_dir must contain a Timelines/<id>/ shell with draft content files"
        )
    return candidates[0]


def resolve_media_path(path_value: str, *, draft_content_path: Path) -> Path | None:
    """Resolve a Jianying media path, including legacy fixture absolute paths by basename."""
    raw = Path(path_value).expanduser()
    if raw.is_absolute() and raw.is_file():
        return raw

    roots = [
        draft_content_path.parent,
        draft_content_path.parent.parent,
        Path.cwd(),
        Path.cwd() / "tests" / "fixtures" / "media",
        Path.cwd() / "tests" / "videos",
    ]
    if not raw.is_absolute():
        for root in roots:
            candidate = root / raw
            if candidate.is_file():
                return candidate

    basename = raw.name
    if not basename:
        return None
    for root in (Path.cwd() / "tests" / "videos", Path.cwd() / "tests" / "fixtures" / "media"):
        candidate = root / basename
        if candidate.is_file():
            return candidate
    return None


__all__ = [
    "DEFAULT_DRAFTS_DIR_CANDIDATES",
    "bundled_template_dir",
    "discover_jianying_drafts_dir",
    "install_report_path",
    "resolve_media_path",
    "slugify_draft_name",
    "template_timeline_dir",
    "unique_draft_dir",
]
