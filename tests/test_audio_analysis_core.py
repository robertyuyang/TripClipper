from __future__ import annotations

import wave
from pathlib import Path

import pytest

from tripclipper.audio_analysis import (
    AudioAnalysisError,
    AudioAnalysisParser,
    AudioChunk,
    AudioExtractionError,
    AudioExtractor,
    _chunk_ranges,
    aggregate_audio_chunks,
)
from tripclipper.models import SpeechQuality


def _write_wav(path: Path, duration: float = 1.0) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\0\0" * int(16_000 * duration))


def test_chunk_ranges_cover_boundaries_without_overlap() -> None:
    assert _chunk_ranges(299.0) == [(0.0, 299.0)]
    assert _chunk_ranges(300.0) == [(0.0, 300.0)]
    assert _chunk_ranges(601.0) == [
        (0.0, 300.0),
        (300.0, 300.0),
        (600.0, 1.0),
    ]


def test_extractor_creates_pcm_cache_and_reuses_matching_source(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    _write_wav(source)
    extractor = AudioExtractor(tmp_path / "cache")

    first = extractor.extract(source, "a1")
    assert len(first) == 1
    assert first[0].start_offset_sec == 0.0
    assert first[0].path.is_file()
    first_mtime = first[0].path.stat().st_mtime_ns

    second = extractor.extract(source, "a1")
    assert second[0].path.stat().st_mtime_ns == first_mtime

    forced = extractor.extract(source, "a1", force=True)
    assert forced[0].path.is_file()


def test_extractor_rejects_source_without_audio(tmp_path: Path) -> None:
    source = tmp_path / "not-media.txt"
    source.write_text("no audio", encoding="utf-8")
    with pytest.raises(AudioExtractionError):
        AudioExtractor(tmp_path / "cache").extract(source, "a1")


def _chunk(offset: float = 300.0, duration: float = 10.0) -> AudioChunk:
    return AudioChunk(Path("chunk.wav"), offset, duration)


def test_parser_drops_invalid_offsets_and_merges_overlaps() -> None:
    result = AudioAnalysisParser().parse(
        {
            "speech_quality": "clear",
            "speech_segments": [
                {"start_sec": 1, "end_sec": 4, "text": "你好"},
                {"start_sec": 3, "end_sec": 6, "text": "世界"},
                {"start_sec": -1, "end_sec": 2, "text": "非法"},
            ],
        },
        _chunk(),
    )
    assert result.speech_quality is SpeechQuality.clear
    assert [(s.start_sec, s.end_sec, s.text) for s in result.speech_segments] == [
        (301.0, 306.0, "你好 世界")
    ]
    assert result.warnings


def test_parser_corrects_contradictory_quality() -> None:
    none_with_segment = AudioAnalysisParser().parse(
        {
            "speech_quality": "none",
            "speech_segments": [{"start_sec": 1, "end_sec": 2, "text": ""}],
        },
        _chunk(0),
    )
    assert none_with_segment.speech_quality is SpeechQuality.unclear

    clear_without_text = AudioAnalysisParser().parse(
        {
            "speech_quality": "clear",
            "speech_segments": [{"start_sec": 1, "end_sec": 2, "text": ""}],
        },
        _chunk(0),
    )
    assert clear_without_text.speech_quality is SpeechQuality.unclear


def test_parser_rejects_untrustworthy_top_level() -> None:
    with pytest.raises(AudioAnalysisError):
        AudioAnalysisParser().parse("not json", _chunk())
    with pytest.raises(AudioAnalysisError):
        AudioAnalysisParser().parse(
            {"speech_quality": "clear", "speech_segments": [{"start_sec": 20, "end_sec": 21, "text": "x"}]},
            _chunk(),
        )


def test_aggregate_complete_and_partial_results() -> None:
    parser = AudioAnalysisParser()
    clear = parser.parse(
        {"speech_quality": "clear", "speech_segments": [{"start_sec": 1, "end_sec": 2, "text": "清晰"}]},
        _chunk(0),
    )
    none = parser.parse(
        {"speech_quality": "none", "speech_segments": []}, _chunk(10)
    )

    complete = aggregate_audio_chunks([none, clear])
    assert complete.speech_quality is SpeechQuality.clear
    assert complete.incomplete is False

    partial_speech = aggregate_audio_chunks([clear, None])
    assert partial_speech.speech_quality is SpeechQuality.clear
    assert partial_speech.incomplete is True

    partial_none = aggregate_audio_chunks([none, None])
    assert partial_none.speech_quality is None
    assert partial_none.incomplete is True

    all_failed = aggregate_audio_chunks([None])
    assert all_failed.speech_quality is None
    assert all_failed.speech_segments == []
