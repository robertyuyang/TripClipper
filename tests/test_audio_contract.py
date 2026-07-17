from __future__ import annotations

import json
from pathlib import Path

import pytest

from tripclipper.config import ConfigError, load_software_config
from tripclipper.cut_index import read_cut_index, write_cut_index
from tripclipper.models import (
    AnalysisInfo,
    Asset,
    ProjectInfo,
    SpeechQuality,
    SpeechSegment,
    TranscriptDocument,
)
from tripclipper.paths import audio_asset_cache_dir, transcripts_dir


def test_audio_models_serialize_with_schema_0_4(tmp_path: Path) -> None:
    from tripclipper.models import CutIndex

    transcript = TranscriptDocument(
        speech_quality=SpeechQuality.clear,
        speech_segments=[SpeechSegment(start_sec=1.2, end_sec=2.8, text="你好")],
    )
    asset = Asset(
        asset_id="asset_1",
        speech_quality=SpeechQuality.clear,
        transcript_path="cache/transcripts/asset_1.json",
    )
    cut = CutIndex(
        project=ProjectInfo(project_name="测试", project_slug="test"),
        analysis=AnalysisInfo(audio_analysis_model="google/gemini-3.5-flash"),
        assets=[asset],
    )
    path = tmp_path / "cut_index.json"
    write_cut_index(path, cut)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "0.4"
    assert raw["assets"][0]["speech_quality"] == "clear"
    assert raw["analysis"]["audio_analysis_model"] == "google/gemini-3.5-flash"
    assert transcript.model_dump(mode="json") == {
        "speech_quality": "clear",
        "speech_segments": [{"start_sec": 1.2, "end_sec": 2.8, "text": "你好"}],
    }


def test_read_legacy_0_3_defaults_audio_fields_and_upgrades_on_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cut_index.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.3",
                "project": {"project_name": "旧项目", "project_slug": "legacy"},
                "analysis": {"vision_model": "vision"},
                "assets": [{"asset_id": "a1", "analysis_status": "analyzed"}],
            }
        ),
        encoding="utf-8",
    )

    cut = read_cut_index(path)
    assert cut.schema_version == "0.4"
    assert cut.analysis.audio_analysis_model is None
    assert cut.assets[0].speech_quality is None

    write_cut_index(path, cut)
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == "0.4"


def test_audio_model_config_is_required_and_legacy_key_is_rejected(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.yaml"
    missing.write_text(
        "model_config:\n  provider: openai_compatible\n  base_url: https://example.test/v1\n"
        "  api_key_env: TEST_KEY\n  vision_model: vision\n",
        encoding="utf-8",
    )
    config = load_software_config(missing)
    assert config.llm.is_audio_analysis_usable() is False

    legacy = tmp_path / "legacy.yaml"
    legacy.write_text(
        "model_config:\n  transcription_model: old-model\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="audio_analysis_model"):
        load_software_config(legacy)


def test_audio_paths_are_project_scoped(tmp_path: Path) -> None:
    assert audio_asset_cache_dir("demo", "a1", tmp_path) == (
        tmp_path / "demo" / "cache" / "audio" / "a1"
    )
    assert transcripts_dir("demo", tmp_path) == tmp_path / "demo" / "cache" / "transcripts"
