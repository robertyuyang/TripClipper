"""Audio extraction, response normalization, and conservative aggregation."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import wave
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .models import SpeechQuality, SpeechSegment

MAX_AUDIO_CHUNK_SECONDS = 300.0
SILENCE_PEAK_DBFS = -75.0
SILENCE_RMS_DBFS = -80.0


class AudioExtractionError(Exception):
    """Raised when a source has no readable audio or ffmpeg extraction fails."""


class AudioAnalysisError(Exception):
    """Raised when a model response cannot establish a trustworthy result."""


def _is_meaningful_speech_text(text: str) -> bool:
    compact = "".join(character for character in text.strip() if not character.isspace())
    if not compact or not any(character.isalnum() for character in compact):
        return False
    return re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?", compact) is None


def _to_dbfs(amplitude: float) -> float:
    if amplitude <= 0:
        return float("-inf")
    return 20.0 * math.log10(amplitude / 32768.0)


def is_near_digital_silence(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getsampwidth() != 2:
                raise AudioAnalysisError("静音检测仅支持 16-bit PCM WAV")
            peak = 0
            square_sum = 0
            sample_count = 0
            while True:
                frames = wav.readframes(65_536)
                if not frames:
                    break
                samples = array("h")
                samples.frombytes(frames)
                if sys.byteorder != "little":
                    samples.byteswap()
                for sample in samples:
                    magnitude = abs(sample)
                    peak = max(peak, magnitude)
                    square_sum += sample * sample
                sample_count += len(samples)
    except (OSError, EOFError, wave.Error) as exc:
        raise AudioAnalysisError(f"静音检测无法读取 WAV：{type(exc).__name__}") from exc
    if sample_count == 0:
        raise AudioAnalysisError("静音检测发现空 WAV")
    rms = math.sqrt(square_sum / sample_count)
    return _to_dbfs(peak) <= SILENCE_PEAK_DBFS and _to_dbfs(rms) <= SILENCE_RMS_DBFS


@dataclass(frozen=True)
class AudioChunk:
    path: Path
    start_offset_sec: float
    duration_sec: float


@dataclass
class ParsedAudioChunk:
    speech_quality: SpeechQuality
    speech_segments: list[SpeechSegment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class AggregatedAudioResult:
    speech_quality: Optional[SpeechQuality]
    speech_segments: list[SpeechSegment] = field(default_factory=list)
    incomplete: bool = False
    all_succeeded: bool = False


def _binary(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    homebrew = Path("/opt/homebrew/bin") / name
    if homebrew.is_file():
        return str(homebrew)
    raise AudioExtractionError(f"未找到 {name}，请先安装 ffmpeg")


def _chunk_ranges(duration_sec: float) -> list[tuple[float, float]]:
    duration = float(duration_sec)
    if duration <= 0:
        return []
    ranges: list[tuple[float, float]] = []
    offset = 0.0
    while offset < duration:
        length = min(MAX_AUDIO_CHUNK_SECONDS, duration - offset)
        ranges.append((round(offset, 6), round(length, 6)))
        offset += length
    return ranges


class AudioExtractor:
    """Extract validated PCM chunks into a fingerprinted per-asset cache."""

    def __init__(self, cache_root: Path) -> None:
        self.cache_root = Path(cache_root)

    def extract(
        self, source: Path, asset_id: str, *, force: bool = False
    ) -> list[AudioChunk]:
        source = Path(source).resolve()
        if not source.is_file():
            raise AudioExtractionError(f"音频源文件不存在：{source}")
        asset_dir = self.cache_root / asset_id
        manifest_path = asset_dir / "manifest.json"
        fingerprint = self._fingerprint(source)

        if not force:
            cached = self._load_cache(manifest_path, fingerprint)
            if cached is not None:
                return cached

        duration = self._probe_duration(source)
        ranges = _chunk_ranges(duration)
        if not ranges:
            raise AudioExtractionError(f"未检测到可提取音轨：{source.name}")

        asset_dir.mkdir(parents=True, exist_ok=True)
        for old in asset_dir.glob("chunk-*.wav"):
            old.unlink()

        chunks: list[AudioChunk] = []
        for index, (offset, length) in enumerate(ranges):
            output = asset_dir / f"chunk-{index:04d}.wav"
            command = [
                _binary("ffmpeg"),
                "-v",
                "error",
                "-y",
                "-ss",
                str(offset),
                "-t",
                str(length),
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(output),
            ]
            completed = subprocess.run(command, capture_output=True, text=True)
            if completed.returncode != 0 or not output.is_file():
                raise AudioExtractionError(
                    f"ffmpeg 音频提取失败：{completed.stderr.strip()[:200]}"
                )
            chunks.append(AudioChunk(output, offset, length))

        manifest = {
            "source_fingerprint": fingerprint,
            "chunks": [
                {
                    "file": chunk.path.name,
                    "start_offset_sec": chunk.start_offset_sec,
                    "duration_sec": chunk.duration_sec,
                }
                for chunk in chunks
            ],
        }
        temporary = manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(manifest_path)
        return chunks

    @staticmethod
    def _fingerprint(source: Path) -> dict[str, Any]:
        stat = source.stat()
        return {
            "path": str(source),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

    @staticmethod
    def _probe_duration(source: Path) -> float:
        command = [
            _binary("ffprobe"),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=duration:format=duration",
            "-of",
            "json",
            str(source),
        ]
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            raise AudioExtractionError(
                f"ffprobe 无法读取音轨：{completed.stderr.strip()[:200]}"
            )
        try:
            payload = json.loads(completed.stdout)
            streams = payload.get("streams") or []
            if not streams:
                raise ValueError("no audio stream")
            raw = streams[0].get("duration") or (payload.get("format") or {}).get("duration")
            duration = float(raw)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise AudioExtractionError(f"未检测到可用音轨：{source.name}") from exc
        if duration <= 0:
            raise AudioExtractionError(f"音轨时长无效：{source.name}")
        return duration

    @staticmethod
    def _load_cache(
        manifest_path: Path, fingerprint: dict[str, Any]
    ) -> Optional[list[AudioChunk]]:
        if not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("source_fingerprint") != fingerprint:
                return None
            chunks = [
                AudioChunk(
                    manifest_path.parent / item["file"],
                    float(item["start_offset_sec"]),
                    float(item["duration_sec"]),
                )
                for item in manifest["chunks"]
            ]
            if not chunks or not all(chunk.path.is_file() and chunk.path.stat().st_size > 44 for chunk in chunks):
                return None
            return chunks
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None


class AudioAnalysisParser:
    """Validate one model response and restore timestamps to source time."""

    def parse(self, payload: str | dict[str, Any], chunk: AudioChunk) -> ParsedAudioChunk:
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise AudioAnalysisError("音频模型响应不是合法 JSON") from exc
        else:
            data = payload
        if not isinstance(data, dict):
            raise AudioAnalysisError("音频模型响应顶层必须是 JSON 对象")
        try:
            quality = SpeechQuality(data["speech_quality"])
        except (KeyError, ValueError, TypeError) as exc:
            raise AudioAnalysisError("speech_quality 缺失或枚举非法") from exc
        raw_segments = data.get("speech_segments")
        if not isinstance(raw_segments, list):
            raise AudioAnalysisError("speech_segments 必须是数组")

        warnings: list[str] = []
        local: list[SpeechSegment] = []
        for index, item in enumerate(raw_segments):
            try:
                start = float(item["start_sec"])
                end = float(item["end_sec"])
                text = str(item.get("text", ""))
            except (TypeError, ValueError, KeyError, AttributeError):
                warnings.append(f"丢弃非法人声片段 {index}")
                continue
            if not (0 <= start < end <= chunk.duration_sec + 1e-6):
                warnings.append(f"丢弃越界人声片段 {index}")
                continue
            local.append(SpeechSegment(start_sec=start, end_sec=end, text=text))

        if raw_segments and not local:
            raise AudioAnalysisError("所有人声片段均非法，无法建立可信分类")

        usable: list[SpeechSegment] = []
        for index, segment in enumerate(local):
            if segment.text.strip() and not _is_meaningful_speech_text(segment.text):
                warnings.append(f"丢弃文本不可用的人声片段 {index}")
                continue
            usable.append(segment)
        local = usable

        local.sort(key=lambda segment: segment.start_sec)
        merged: list[SpeechSegment] = []
        for segment in local:
            if merged and segment.start_sec <= merged[-1].end_sec:
                previous = merged[-1]
                texts = [text for text in (previous.text.strip(), segment.text.strip()) if text]
                merged[-1] = SpeechSegment(
                    start_sec=previous.start_sec,
                    end_sec=max(previous.end_sec, segment.end_sec),
                    text=" ".join(texts),
                )
            else:
                merged.append(segment)

        if quality is SpeechQuality.none and merged:
            quality = SpeechQuality.unclear
            warnings.append("none 与合法人声片段矛盾，已纠正为 unclear")
        if quality is SpeechQuality.clear and not any(s.text.strip() for s in merged):
            quality = SpeechQuality.unclear
            warnings.append("clear 未包含可辨认文本，已降为 unclear")

        global_segments = [
            SpeechSegment(
                start_sec=round(segment.start_sec + chunk.start_offset_sec, 6),
                end_sec=round(segment.end_sec + chunk.start_offset_sec, 6),
                text=segment.text,
            )
            for segment in merged
        ]
        return ParsedAudioChunk(quality, global_segments, warnings)


def aggregate_audio_chunks(
    chunks: list[Optional[ParsedAudioChunk]],
) -> AggregatedAudioResult:
    successes = [chunk for chunk in chunks if chunk is not None]
    incomplete = len(successes) != len(chunks)
    segments = sorted(
        [segment for chunk in successes for segment in chunk.speech_segments],
        key=lambda segment: segment.start_sec,
    )
    if not successes:
        return AggregatedAudioResult(None, [], True, False)
    if any(chunk.speech_quality is SpeechQuality.clear for chunk in successes):
        quality: Optional[SpeechQuality] = SpeechQuality.clear
    elif any(
        chunk.speech_quality is SpeechQuality.unclear or chunk.speech_segments
        for chunk in successes
    ):
        quality = SpeechQuality.unclear
    elif incomplete:
        quality = None
    else:
        quality = SpeechQuality.none
    return AggregatedAudioResult(quality, segments, incomplete, not incomplete)


__all__ = [
    "MAX_AUDIO_CHUNK_SECONDS",
    "SILENCE_PEAK_DBFS",
    "SILENCE_RMS_DBFS",
    "AudioExtractionError",
    "AudioAnalysisError",
    "AudioChunk",
    "is_near_digital_silence",
    "ParsedAudioChunk",
    "AggregatedAudioResult",
    "AudioExtractor",
    "AudioAnalysisParser",
    "aggregate_audio_chunks",
]
