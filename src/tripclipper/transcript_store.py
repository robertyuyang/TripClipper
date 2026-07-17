"""Validated atomic persistence for per-asset transcript documents."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from .models import Asset, TranscriptDocument


class TranscriptStoreError(Exception):
    pass


class TranscriptStore:
    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir)

    def save(
        self, asset: Asset, document: TranscriptDocument, *, complete: bool
    ) -> bool:
        if not asset.asset_id:
            raise TranscriptStoreError("asset_id 缺失，无法保存转写")
        target = self.project_dir / "cache" / "transcripts" / f"{asset.asset_id}.json"
        if not complete and self._is_valid_existing(target):
            return False
        old_path = asset.transcript_path
        old_quality = asset.speech_quality
        temporary = target.with_suffix(".json.tmp")
        try:
            validated = TranscriptDocument.model_validate(
                document.model_dump(mode="json")
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(validated.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            TranscriptDocument.model_validate_json(temporary.read_text(encoding="utf-8"))
            temporary.replace(target)
        except (OSError, ValidationError, ValueError) as exc:
            if temporary.exists():
                temporary.unlink()
            asset.transcript_path = old_path
            asset.speech_quality = old_quality
            raise TranscriptStoreError(f"转写文件校验或写入失败：{type(exc).__name__}") from exc
        asset.transcript_path = target.relative_to(self.project_dir).as_posix()
        asset.speech_quality = validated.speech_quality
        return True

    @staticmethod
    def _is_valid_existing(path: Path) -> bool:
        if not path.is_file():
            return False
        try:
            TranscriptDocument.model_validate_json(path.read_text(encoding="utf-8"))
            return True
        except (OSError, ValidationError, ValueError):
            return False


__all__ = ["TranscriptStoreError", "TranscriptStore"]
