from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tripclipper.audio_analysis import AudioChunk
from tripclipper.audio_provider import AudioAnalysisProvider, AudioProviderError
from tripclipper.config import ModelConfig
from tripclipper.models import (
    Asset,
    SpeechQuality,
    SpeechSegment,
    TranscriptDocument,
)
from tripclipper.transcript_store import TranscriptStore, TranscriptStoreError


def _config() -> ModelConfig:
    return ModelConfig(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key_env="TEST_AUDIO_KEY",
        vision_model="vision",
        audio_analysis_model="google/gemini-3.5-flash",
    )


def _chunk(tmp_path: Path) -> AudioChunk:
    path = tmp_path / "chunk.wav"
    path.write_bytes(b"RIFF" + b"audio-bytes")
    return AudioChunk(path, 0.0, 3.0)


def test_audio_provider_sends_input_audio_and_original_language_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_AUDIO_KEY", "secret")
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"speech_quality": "none", "speech_segments": []}
                            )
                        }
                    }
                ]
            },
        )

    provider = AudioAnalysisProvider(
        _config(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = provider.analyze(_chunk(tmp_path))

    assert result["speech_quality"] == "none"
    payload = captured[0]
    assert payload["model"] == "google/gemini-3.5-flash"
    content = payload["messages"][0]["content"]
    audio = next(item for item in content if item["type"] == "input_audio")
    assert audio["input_audio"]["format"] == "wav"
    prompt = next(item["text"] for item in content if item["type"] == "text")
    assert "原语言" in prompt
    assert "不翻译" in prompt
    assert "人类口语" in prompt
    assert "摘要" in prompt


def test_audio_provider_removes_unsupported_reasoning_effort_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_AUDIO_KEY", "secret")
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        payloads.append(payload)
        if len(payloads) == 1:
            return httpx.Response(400, text="reasoning_effort unsupported")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"speech_quality":"none","speech_segments":[]}'}}]},
        )

    provider = AudioAnalysisProvider(
        _config(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    provider.analyze(_chunk(tmp_path))
    assert "reasoning_effort" in payloads[0]
    assert "reasoning_effort" not in payloads[1]
    assert len(payloads) == 2


def test_audio_provider_retries_transient_without_leaking_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_AUDIO_KEY", "secret")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="secret input_audio huge-base64")

    provider = AudioAnalysisProvider(
        _config(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _seconds: None,
    )
    with pytest.raises(AudioProviderError) as exc_info:
        provider.analyze(_chunk(tmp_path))
    assert calls == 3
    message = str(exc_info.value)
    assert "secret" not in message
    assert "input_audio" not in message


def test_transcript_store_publishes_then_updates_asset(tmp_path: Path) -> None:
    asset = Asset(asset_id="a1")
    document = TranscriptDocument(
        speech_quality=SpeechQuality.clear,
        speech_segments=[SpeechSegment(start_sec=1, end_sec=2, text="你好")],
    )
    store = TranscriptStore(tmp_path)

    assert store.save(asset, document, complete=True) is True
    path = tmp_path / "cache" / "transcripts" / "a1.json"
    assert json.loads(path.read_text(encoding="utf-8"))["speech_segments"][0]["text"] == "你好"
    assert asset.transcript_path == "cache/transcripts/a1.json"
    assert asset.speech_quality is SpeechQuality.clear
    assert not list(path.parent.glob("*.tmp"))


def test_transcript_store_rejects_invalid_document_without_mutation(tmp_path: Path) -> None:
    asset = Asset(asset_id="a1", speech_quality=SpeechQuality.clear, transcript_path="old.json")
    store = TranscriptStore(tmp_path)
    invalid = TranscriptDocument.model_construct(
        speech_quality=SpeechQuality.clear,
        speech_segments=[SpeechSegment.model_construct(start_sec=3, end_sec=2, text="bad")],
    )
    with pytest.raises(TranscriptStoreError):
        store.save(asset, invalid, complete=True)
    assert asset.transcript_path == "old.json"
    assert asset.speech_quality is SpeechQuality.clear


def test_partial_result_does_not_replace_existing_valid_transcript(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    asset = Asset(asset_id="a1")
    old = TranscriptDocument(speech_quality=SpeechQuality.clear, speech_segments=[])
    store.save(asset, old, complete=True)
    path = tmp_path / "cache" / "transcripts" / "a1.json"
    before = path.read_bytes()

    partial = TranscriptDocument(
        speech_quality=SpeechQuality.unclear,
        speech_segments=[SpeechSegment(start_sec=4, end_sec=5, text="部分")],
    )
    assert store.save(asset, partial, complete=False) is False
    assert path.read_bytes() == before
