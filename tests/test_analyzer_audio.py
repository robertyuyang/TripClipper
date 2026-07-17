from __future__ import annotations

from pathlib import Path

from tripclipper.analyzer import _analyze_asset_audio, _should_process
from tripclipper.audio_analysis import AudioChunk, AudioExtractionError
from tripclipper.models import AnalysisStatus, Asset, AssetType, SpeechQuality


class _Extractor:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def extract(self, _source: Path, _asset_id: str, *, force: bool = False):
        self.calls += 1
        if self.fail:
            raise AudioExtractionError("boom")
        return [AudioChunk(Path("chunk.wav"), 0, 10)]


class _Provider:
    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, _chunk: AudioChunk):
        self.calls += 1
        return {
            "speech_quality": "clear",
            "speech_segments": [{"start_sec": 1, "end_sec": 2, "text": "你好"}],
        }


class _Store:
    def __init__(self) -> None:
        self.calls = 0

    def save(self, asset: Asset, document, *, complete: bool):
        self.calls += 1
        asset.speech_quality = document.speech_quality
        asset.transcript_path = f"cache/transcripts/{asset.asset_id}.json"
        return True


def test_no_audio_video_sets_none_without_calling_dependencies() -> None:
    asset = Asset(
        asset_id="v1",
        type=AssetType.video,
        metadata={"has_audio": False},
        analysis_status=AnalysisStatus.analyzed,
    )
    extractor, provider, store = _Extractor(), _Provider(), _Store()
    error = _analyze_asset_audio(
        asset,
        source_path=Path("video.mp4"),
        extractor=extractor,
        provider=provider,
        store=store,
    )
    assert error is None
    assert asset.speech_quality is SpeechQuality.none
    assert asset.transcript_path is None
    assert (extractor.calls, provider.calls, store.calls) == (0, 0, 0)


def test_standalone_audio_asset_is_ignored() -> None:
    asset = Asset(asset_id="a1", type=AssetType.audio, metadata={"has_audio": True})
    extractor, provider, store = _Extractor(), _Provider(), _Store()
    assert _analyze_asset_audio(
        asset,
        source_path=Path("audio.wav"),
        extractor=extractor,
        provider=provider,
        store=store,
    ) is None
    assert (extractor.calls, provider.calls, store.calls) == (0, 0, 0)


def test_video_audio_is_analyzed_and_persisted() -> None:
    asset = Asset(asset_id="v1", type=AssetType.video, metadata={"has_audio": True})
    extractor, provider, store = _Extractor(), _Provider(), _Store()
    assert _analyze_asset_audio(
        asset,
        source_path=Path("video.mp4"),
        extractor=extractor,
        provider=provider,
        store=store,
    ) is None
    assert asset.speech_quality is SpeechQuality.clear
    assert asset.transcript_path == "cache/transcripts/v1.json"
    assert (extractor.calls, provider.calls, store.calls) == (1, 1, 1)


def test_audio_failure_preserves_successful_visual_status() -> None:
    asset = Asset(
        asset_id="v1",
        type=AssetType.video,
        metadata={"has_audio": True},
        analysis_status=AnalysisStatus.analyzed,
        summary="画面结果",
    )
    error = _analyze_asset_audio(
        asset,
        source_path=Path("video.mp4"),
        extractor=_Extractor(fail=True),
        provider=_Provider(),
        store=_Store(),
    )
    assert "boom" in (error or "")
    assert asset.analysis_status is AnalysisStatus.analyzed
    assert asset.summary == "画面结果"
    assert asset.speech_quality is None
    assert asset.failures[-1]["blocking"] is False


def test_analyzed_video_with_missing_audio_result_remains_eligible() -> None:
    pending = Asset(
        asset_id="v1",
        type=AssetType.video,
        metadata={"has_audio": True},
        analysis_status=AnalysisStatus.analyzed,
        speech_quality=None,
    )
    done = pending.model_copy(update={"speech_quality": SpeechQuality.clear})
    assert _should_process(pending, force=False) is True
    assert _should_process(done, force=False) is False
