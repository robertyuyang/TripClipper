"""项目素材范围查看适配器。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from tripclipper.scan import _invoke_ffmpeg, _resolve_media_tool

from .contracts import FrameObservation, ProjectSnapshot


RangeExtractor = Callable[[Path, float, float, Path, str], list[Path]]


def _extract_range(source: Path, start: float, end: float, out_dir: Path, stem: str) -> list[Path]:
    ffmpeg = _resolve_media_tool("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg 不可用")
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = end - start
    timestamps = [start + duration * fraction for fraction in (0.2, 0.5, 0.8)]
    frames: list[Path] = []
    for index, timestamp in enumerate(timestamps, start=1):
        target = out_dir / f"{stem}_{start:g}_{end:g}_{index}.jpg"
        command = [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale=480:-2",
            str(target),
        ]
        _invoke_ffmpeg(command, label=f"选片范围帧 {stem}@{timestamp:.3f}")
        if target.is_file():
            frames.append(target)
    if not frames:
        raise RuntimeError("范围查看未生成帧")
    return frames


class ProjectFrameSource:
    def __init__(
        self,
        snapshot: ProjectSnapshot,
        cache_dir: str | Path,
        *,
        extractor: RangeExtractor = _extract_range,
    ) -> None:
        self.snapshot = snapshot
        self.cache_dir = Path(cache_dir)
        self.extractor = extractor

    def inspect(self, asset_id: str, start_sec: float, end_sec: float) -> FrameObservation:
        asset = self.snapshot.asset(asset_id)
        if start_sec < 0 or end_sec <= start_sec:
            raise ValueError("查看范围非法")
        existing: list[str] = []
        for frame_path, timestamp in zip(asset.frame_paths, asset.frame_timestamps):
            path = Path(frame_path)
            if not path.is_absolute():
                path = self.snapshot.cut_index_path.parent / path
            if start_sec <= timestamp <= end_sec and path.is_file():
                existing.append(str(path))
        if existing:
            return FrameObservation(
                asset_id=asset_id,
                start_sec=start_sec,
                end_sec=end_sec,
                frame_paths=existing,
                description=f"命中 {len(existing)} 张已有帧",
            )
        source = self._source_path(asset.path, asset.relative_path)
        frames = self.extractor(
            source,
            start_sec,
            end_sec,
            self.cache_dir / asset_id,
            asset_id,
        )
        return FrameObservation(
            asset_id=asset_id,
            start_sec=start_sec,
            end_sec=end_sec,
            frame_paths=[str(path) for path in frames],
            description=f"追加抽取 {len(frames)} 张范围帧",
        )

    def _source_path(self, absolute: str | None, relative: str | None) -> Path:
        candidates: list[Path] = []
        if absolute:
            candidates.append(Path(absolute))
        if relative and self.snapshot.source_folder:
            candidates.append(Path(self.snapshot.source_folder) / relative)
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise ValueError("素材源文件不可读")

