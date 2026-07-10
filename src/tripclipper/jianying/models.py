"""Public models for Jianying draft installation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

ValidationStatus = Literal["ok", "error"]


@dataclass(frozen=True)
class DraftInstallRequest:
    """Request to install an existing Jianying ``draft_content.json``."""

    draft_content_path: Path | str
    draft_name: str
    template_draft_dir: Path | str | None = None
    jianying_drafts_dir: Path | str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "draft_content_path", Path(self.draft_content_path))
        if self.template_draft_dir is not None:
            object.__setattr__(self, "template_draft_dir", Path(self.template_draft_dir))
        if self.jianying_drafts_dir is not None:
            object.__setattr__(self, "jianying_drafts_dir", Path(self.jianying_drafts_dir))


@dataclass(frozen=True)
class InstallValidationItem:
    """One validation or install check emitted by the installer."""

    name: str
    status: ValidationStatus
    message: str
    path: Path | str | None = None

    def to_report(self) -> dict[str, str | None]:
        payload = asdict(self)
        if self.path is not None:
            payload["path"] = str(self.path)
        return payload


@dataclass(frozen=True)
class DraftInstallResult:
    """Result of a successful Jianying draft install."""

    draft_dir: Path
    timeline_id: str
    report_path: Path
    copied_media_paths: dict[str, Path] = field(default_factory=dict)
    validation_items: list[InstallValidationItem] = field(default_factory=list)

    def to_report(self) -> dict[str, object]:
        return {
            "draft_dir": str(self.draft_dir),
            "timeline_id": self.timeline_id,
            "report_path": str(self.report_path),
            "copied_media_paths": {
                str(source): str(target) for source, target in self.copied_media_paths.items()
            },
            "validation_items": [item.to_report() for item in self.validation_items],
        }


class DraftInstallError(RuntimeError):
    """Raised when a draft cannot be safely installed."""

    def __init__(
        self,
        message: str,
        *,
        validation_items: list[InstallValidationItem] | None = None,
        report_path: Path | None = None,
        draft_dir: Path | None = None,
        timeline_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.validation_items = validation_items or []
        self.report_path = report_path
        self.draft_dir = draft_dir
        self.timeline_id = timeline_id


__all__ = [
    "DraftInstallRequest",
    "InstallValidationItem",
    "DraftInstallResult",
    "DraftInstallError",
]
