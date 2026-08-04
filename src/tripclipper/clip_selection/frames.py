"""按需抽取并跨选片任务复用视觉证据帧。"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any, Callable

from tripclipper.models import Asset
from tripclipper.scan import _invoke_ffmpeg, _resolve_media_tool

from .models import SampledRange, SelectionState
from .store import SelectionStore


FrameExtractor = Callable[[Path, float, Path], Path]


def _extract_frame(source: Path, timestamp: float, target: Path) -> Path:
    ffmpeg = _resolve_media_tool("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg 不可用，无法追加抽取选片帧")
    target.parent.mkdir(parents=True, exist_ok=True)
    _invoke_ffmpeg(
        [
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
            "scale=768:-2",
            str(target),
        ],
        label=f"选片采样帧 {source}@{timestamp:.3f}",
    )
    if not target.is_file():
        raise RuntimeError(f"ffmpeg 未生成选片采样帧：{target}")
    return target


class FrameSampler:
    def __init__(
        self,
        assets: dict[str, Asset],
        state: SelectionState,
        store: SelectionStore,
        shared_dir: Path,
        *,
        source_folder: str | Path | None = None,
        extractor: FrameExtractor = _extract_frame,
    ) -> None:
        self.assets = assets
        self.state = state
        self.store = store
        self.shared_dir = shared_dir
        self.source_folder = Path(source_folder) if source_folder else None
        self.extractor = extractor

    def sample(
        self,
        asset_id: str,
        start_sec: float,
        end_sec: float,
        count: int,
    ) -> dict[str, Any]:
        asset = self.assets.get(asset_id)
        if asset is None:
            raise ValueError(f"素材不存在：{asset_id}")
        duration = asset.metadata.get("duration")
        if not isinstance(duration, (int, float)) or duration <= 0:
            raise ValueError(f"素材缺少有效时长：{asset_id}")
        if not 0 <= start_sec < end_sec <= float(duration):
            raise ValueError(
                f"采样范围必须满足 0 <= start_sec < end_sec <= {float(duration):g}"
            )
        if not 1 <= count <= 12:
            raise ValueError("count 必须位于 1～12")

        available = self._available_frames(asset, start_sec, end_sec)
        targets = [
            start_sec + (end_sec - start_sec) * (index + 1) / (count + 1)
            for index in range(count)
        ]
        selected: list[dict[str, Any]] = []
        unused = list(available)
        if len(unused) >= count:
            for target in targets:
                nearest = min(
                    unused,
                    key=lambda item: abs(item["timestamp_sec"] - target),
                )
                selected.append(nearest)
                unused.remove(nearest)
        else:
            selected.extend(unused)
        for target in targets:
            if len(selected) >= count:
                break
            if any(
                abs(item["timestamp_sec"] - target) < 1e-6 for item in selected
            ):
                continue
            path = self.shared_dir / self._shared_filename(asset_id, target)
            source_path = self._source_path(asset)
            self.extractor(source_path, target, path)
            selected.append(
                {
                    "path": str(path),
                    "timestamp_sec": float(target),
                    "source": "shared_extracted",
                }
            )
        selected.sort(key=lambda item: item["timestamp_sec"])

        record = SampledRange(
            asset_id=asset_id,
            start_sec=start_sec,
            end_sec=end_sec,
            count=count,
            frame_paths=[item["path"] for item in selected],
        )
        self.state.asset_progress.sampled_ranges.append(record)
        self.store.save(self.state)
        result = {
            "asset_id": asset_id,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "count": count,
            "frames": selected,
        }
        self.store.append_event(
            "asset_frames_sampled",
            tool="asset_frames_sample",
            data=result,
        )
        return result

    def tool_content(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        frames = result["frames"]
        metadata = {
            **{key: result[key] for key in ("asset_id", "start_sec", "end_sec", "count")},
            "frames": [
                {
                    "path": frame["path"],
                    "timestamp_sec": frame["timestamp_sec"],
                    "source": frame["source"],
                }
                for frame in frames
            ],
        }
        content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": json.dumps(metadata, ensure_ascii=False),
            }
        ]
        for frame in frames:
            content.append(
                {
                    "type": "input_image",
                    "image_url": self._data_url(Path(frame["path"])),
                    "detail": "high",
                }
            )
        return content

    def _available_frames(
        self,
        asset: Asset,
        start_sec: float,
        end_sec: float,
    ) -> list[dict[str, Any]]:
        frames: list[dict[str, Any]] = []
        for raw_path, timestamp in zip(asset.frame_paths, asset.frame_timestamps):
            path = self._resolve_existing_path(raw_path)
            if path.is_file() and start_sec <= timestamp <= end_sec:
                frames.append(
                    {
                        "path": str(path),
                        "timestamp_sec": float(timestamp),
                        "source": "cut_index",
                    }
                )
        prefix = self._asset_prefix(asset.asset_id or "")
        for path in sorted(self.shared_dir.glob(f"{prefix}__*.jpg")):
            raw_timestamp = path.stem.rsplit("__", 1)[-1]
            try:
                timestamp = int(raw_timestamp) / 1_000_000
            except ValueError:
                continue
            if start_sec <= timestamp <= end_sec:
                frames.append(
                    {
                        "path": str(path),
                        "timestamp_sec": timestamp,
                        "source": "shared_reused",
                    }
                )
        return frames

    def _source_path(self, asset: Asset) -> Path:
        if asset.path:
            path = Path(asset.path)
        elif self.source_folder is not None and asset.relative_path:
            path = self.source_folder / asset.relative_path
        else:
            raise ValueError(f"素材缺少可读取的原视频路径：{asset.asset_id}")
        if not path.is_file():
            raise ValueError(f"原视频不存在：{path}")
        return path

    def _resolve_existing_path(self, raw_path: str) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            return path
        project_dir = self.shared_dir.parent.parent
        return project_dir / path

    @classmethod
    def _shared_filename(cls, asset_id: str, timestamp: float) -> str:
        return f"{cls._asset_prefix(asset_id)}__{round(timestamp * 1_000_000):012d}.jpg"

    @staticmethod
    def _asset_prefix(asset_id: str) -> str:
        return hashlib.sha256(asset_id.encode()).hexdigest()[:16]

    @staticmethod
    def _data_url(path: Path) -> str:
        mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"


__all__ = ["FrameSampler"]
