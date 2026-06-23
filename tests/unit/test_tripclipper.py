from __future__ import annotations

import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from tripclipper.analyzer import analyze_project
from tripclipper.config import create_project_config, load_project_config
from tripclipper.eagle import eagle_dry_run, replace_managed_note_block
from tripclipper.exporter import export_project
from tripclipper.index import load_index
from tripclipper.model_provider import ModelProvider, ModelProviderError, validate_analysis_result
from tripclipper.postprocess import apply_postprocessing
from tripclipper.transcriber import transcribe_project
from tripclipper.web import _model_errors


class FakeProvider(ModelProvider):
    def analyze_asset(self, project, asset):
        ratings = {
            "clip_20260612120000.mp4": 5,
            "clip_20260612120100.mp4": 5,
            "clip_20260612120200.mp4": 2,
            "wide_20260612150000.mp4": 4,
        }
        rating = ratings.get(asset["file"], 4)
        subject = "海边夕阳人物" if asset["file"].startswith("clip_") else "街道路牌"
        shot_function = "highlight" if asset["file"].startswith("clip_") else "transition"
        subject_type = "people_landscape" if asset["file"].startswith("clip_") else "building"
        shot_scale = "medium" if asset["file"].startswith("clip_") else "wide"
        return {
            "summary": f"{asset['file']} 的真实模型测试分析。",
            "tags": ["海边", "人物"] if asset["file"].startswith("clip_") else ["街景", "转场"],
            "rating": rating,
            "scene": subject,
            "subject_type": subject_type,
            "primary_subject": subject,
            "people_presence": "single" if asset["file"].startswith("clip_") else "none",
            "shot_scale": shot_scale,
            "shot_function": shot_function,
            "audio_suggestion": "保留环境声",
            "audio_strategy": "keep_ambient",
            "segments": [
                {
                    "in": "00:00:00",
                    "out": "00:00:05",
                    "role": shot_function,
                    "subject_type": subject_type,
                    "shot_scale": shot_scale,
                    "rating": rating,
                    "reason": "测试片段可用。",
                    "audio_strategy": "keep_ambient",
                    "tags": ["测试"],
                }
            ],
        }


class FakeTranscriptionProvider(FakeProvider):
    def __init__(self):
        self.transcribed_audio_paths = []
        self.saw_transcript_before_analysis = False

    def transcribe_audio(self, audio_path):
        path = Path(audio_path)
        if not path.exists():
            raise AssertionError("expected extracted audio file to exist")
        self.transcribed_audio_paths.append(path)
        return "你好，TripClipper。"

    def analyze_asset(self, project, asset):
        transcript_path = asset.get("transcript_path")
        self.saw_transcript_before_analysis = bool(
            transcript_path and Path(transcript_path).read_text(encoding="utf-8").strip() == "你好，TripClipper。"
        )
        return super().analyze_asset(project, asset)


class TripClipperTests(unittest.TestCase):
    def test_config_creation_and_loading_omits_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "media"
            source.mkdir()
            config_path = create_project_config(
                {
                    "project_name": "我的旅行",
                    "source_folder": str(source),
                    "model_config": {
                        "provider": "openai_compatible",
                        "base_url": "https://example.com/v1",
                        "api_key_env": "TRIPCLIPPER_MODEL_API_KEY",
                        "api_key": "secret",
                        "vision_model": "vision",
                    },
                },
                base_dir=tmp,
            )
            config = load_project_config(config_path)
            self.assertTrue(config.project_slug.startswith("project-"))
            self.assertNotIn("api_key", config.model_config_summary)
            self.assertNotIn("secret", config_path.read_text(encoding="utf-8"))
            self.assertEqual(config.source_folder, source.resolve())

    def test_project_config_uses_env_model_defaults_without_writing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "media"
            source.mkdir()
            (Path(tmp) / ".env").write_text(
                "\n".join(
                    [
                        "TRIPCLIPPER_MODEL_BASE_URL=https://open.cherryin.ai/v1",
                        "TRIPCLIPPER_MODEL_API_KEY_ENV=TRIPCLIPPER_MODEL_API_KEY",
                        "TRIPCLIPPER_MODEL_API_KEY=secret-from-env",
                        "TRIPCLIPPER_VISION_MODEL=google/gemini-3.5-flash",
                        "TRIPCLIPPER_TEXT_MODEL=google/gemini-3.5-flash",
                        "TRIPCLIPPER_TRANSCRIPTION_MODEL=whisper-1",
                    ]
                ),
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {}, clear=True):
                config_path = create_project_config(
                    {"project_name": "Env Model", "source_folder": str(source)},
                    base_dir=tmp,
                )
                config = load_project_config(config_path)

            self.assertEqual(config.model_config["base_url"], "https://open.cherryin.ai/v1")
            self.assertEqual(config.model_config["vision_model"], "google/gemini-3.5-flash")
            self.assertEqual(config.model_config["transcription_model"], "whisper-1")
            self.assertNotIn("secret-from-env", config_path.read_text(encoding="utf-8"))

    def test_project_status_prefers_project_config_over_stale_index_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "media"
            source.mkdir()
            (Path(tmp) / ".env").write_text(
                "\n".join(
                    [
                        "TRIPCLIPPER_MODEL_BASE_URL=https://open.cherryin.ai/v1",
                        "TRIPCLIPPER_MODEL_API_KEY_ENV=TRIPCLIPPER_MODEL_API_KEY",
                        "TRIPCLIPPER_MODEL_API_KEY=secret-from-env",
                        "TRIPCLIPPER_VISION_MODEL=google/gemini-3.5-flash",
                    ]
                ),
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {}, clear=True):
                config_path = create_project_config(
                    {"project_name": "Status Model", "source_folder": str(source)},
                    base_dir=tmp,
                )
                stale_index = {
                    "project": {
                        "model_config_summary": {
                            "provider": "openai_compatible",
                            "base_url": None,
                            "api_key_env": "TRIPCLIPPER_MODEL_API_KEY",
                            "vision_model": None,
                            "text_model": None,
                        }
                    }
                }

                self.assertEqual(_model_errors(stale_index, Path(config_path).parent), [])

    def test_scan_finds_supported_media_and_skips_other_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "media"
            source.mkdir()
            (source / "a.mp4").write_bytes(b"video")
            (source / "b.txt").write_text("skip", encoding="utf-8")
            config_path = create_project_config({"project_name": "Scan Test", "source_folder": str(source)}, base_dir=tmp)

            data = analyze_project(config_path, "scan")

            self.assertEqual(len(data["assets"]), 1)
            self.assertEqual(data["assets"][0]["file"], "a.mp4")
            self.assertEqual(data["assets"][0]["analysis_status"], "scanned")

    def test_missing_model_config_fails_stage2_without_fake_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "media"
            source.mkdir()
            (source / "a.mp4").write_bytes(b"video")
            config_path = create_project_config({"project_name": "Missing Model", "source_folder": str(source)}, base_dir=tmp)
            analyze_project(config_path, "scan")

            data = analyze_project(config_path, "sample")

            self.assertEqual(data["analysis"]["status"], "failed")
            self.assertEqual(data["assets"][0]["analysis_status"], "scanned")
            self.assertIsNone(data["assets"][0]["summary"])

    def test_transcribe_project_extracts_audio_and_writes_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "media"
            source.mkdir()
            (source / "clip.mp4").write_bytes(b"video")
            config_path = create_project_config({"project_name": "Audio Text", "source_folder": str(source)}, base_dir=tmp)
            analyze_project(config_path, "scan")

            def fake_run(command, **kwargs):
                Path(command[-1]).write_bytes(b"wav")
                return subprocess.CompletedProcess(command, 0, "", "")

            provider = FakeTranscriptionProvider()
            with mock.patch("tripclipper.transcriber.shutil.which", return_value="/usr/bin/ffmpeg"):
                with mock.patch("tripclipper.transcriber.subprocess.run", side_effect=fake_run):
                    data = transcribe_project(config_path, provider=provider)

            asset = data["assets"][0]
            self.assertEqual(data["transcription"]["status"], "completed")
            self.assertEqual(asset["transcription_status"], "transcribed")
            self.assertEqual(Path(asset["transcript_path"]).read_text(encoding="utf-8").strip(), "你好，TripClipper。")
            self.assertEqual(len(provider.transcribed_audio_paths), 1)

    def test_stage2_uses_transcription_model_to_prepare_transcript_before_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "media"
            source.mkdir()
            (source / "clip.mp4").write_bytes(b"video")
            config_path = create_project_config(
                {
                    "project_name": "Auto Transcribe",
                    "source_folder": str(source),
                    "model_config": {"transcription_model": "whisper-1"},
                },
                base_dir=tmp,
            )
            analyze_project(config_path, "scan")

            def fake_run(command, **kwargs):
                Path(command[-1]).write_bytes(b"wav")
                return subprocess.CompletedProcess(command, 0, "", "")

            provider = FakeTranscriptionProvider()
            with mock.patch("tripclipper.transcriber.shutil.which", return_value="/usr/bin/ffmpeg"):
                with mock.patch("tripclipper.transcriber.subprocess.run", side_effect=fake_run):
                    data = analyze_project(config_path, "full", provider=provider)

            self.assertEqual(data["analysis"]["status"], "completed")
            self.assertEqual(data["transcription"]["status"], "completed")
            self.assertTrue(provider.saw_transcript_before_analysis)

    def test_stage2_postprocess_export_and_eagle_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "media"
            source.mkdir()
            for name in [
                "clip_20260612120000.mp4",
                "clip_20260612120100.mp4",
                "clip_20260612120200.mp4",
                "wide_20260612150000.mp4",
            ]:
                (source / name).write_bytes(name.encode("utf-8"))
            config_path = create_project_config(
                {
                    "project_name": "Full Flow",
                    "source_folder": str(source),
                    "model_config": {"sample_size": 25},
                },
                base_dir=tmp,
            )
            analyze_project(config_path, "scan")

            data = analyze_project(config_path, "full", provider=FakeProvider())

            self.assertEqual(data["analysis"]["status"], "completed")
            self.assertEqual(len(data["similar_groups"]), 1)
            statuses = {asset["file"]: asset["edit_candidate_status"] for asset in data["assets"]}
            self.assertEqual(statuses["clip_20260612120000.mp4"], "default_selected")
            self.assertEqual(statuses["clip_20260612120100.mp4"], "alternate")
            self.assertEqual(statuses["clip_20260612120200.mp4"], "excluded")
            self.assertEqual(statuses["wide_20260612150000.mp4"], "default_selected")

            paths = export_project("full-flow", base_dir=tmp)
            self.assertTrue(Path(paths["assets_csv"]).exists())
            self.assertTrue(Path(paths["segments_csv"]).exists())
            self.assertTrue(Path(paths["summary_md"]).exists())
            self.assertTrue(Path(paths["review_html"]).exists())

            plan = eagle_dry_run("full-flow", base_dir=tmp)
            self.assertEqual(plan["mode"], "preview")
            self.assertTrue(plan["assets"][0]["tags_to_add"])

    def test_postprocess_groups_same_scene_when_subject_words_vary(self):
        data = {
            "assets": [
                {
                    "asset_id": "asset_inn_1",
                    "file": "NO20250612-114146-064576F.mp4",
                    "type": "video",
                    "analysis_status": "analyzed",
                    "rating": 2,
                    "scene": "民宿到达",
                    "subject_type": "building",
                    "primary_subject": "民宿白色建筑与门前绿植",
                    "shot_scale": "wide",
                    "shot_function": "establishing",
                    "tags": ["行车记录仪", "民宿外观", "环境"],
                    "audio_strategy": "mute_or_low_ambient",
                },
                {
                    "asset_id": "asset_inn_2",
                    "file": "NO20250612-114246-064577F.mp4",
                    "type": "video",
                    "analysis_status": "analyzed",
                    "rating": 3,
                    "scene": "抵达民宿",
                    "subject_type": "building",
                    "primary_subject": "白色度假屋与木质围栏",
                    "shot_scale": "wide",
                    "shot_function": "establishing",
                    "tags": ["行车记录仪", "民宿", "建筑外观"],
                    "audio_strategy": "mute_or_low_ambient",
                },
                {
                    "asset_id": "asset_inn_3",
                    "file": "NO20250612-114346-064578F.mp4",
                    "type": "video",
                    "analysis_status": "analyzed",
                    "rating": 2,
                    "scene": "抵达民宿",
                    "subject_type": "building",
                    "primary_subject": "民宿建筑外观与门前绣球花",
                    "shot_scale": "wide",
                    "shot_function": "establishing",
                    "tags": ["行车记录仪", "到达", "度假村", "外景"],
                    "audio_strategy": "mute_or_low_ambient",
                },
                {
                    "asset_id": "asset_road",
                    "file": "NO20250612-184330-064596F.mp4",
                    "type": "video",
                    "analysis_status": "analyzed",
                    "rating": 3,
                    "scene": "山区公路行驶",
                    "subject_type": "landscape",
                    "primary_subject": "山区公路与雄伟的岩石山脉",
                    "shot_scale": "wide",
                    "shot_function": "transition",
                    "tags": ["行车记录仪", "山区公路", "过渡镜头"],
                    "audio_strategy": "mute_or_low_ambient",
                },
            ]
        }

        apply_postprocessing(data)

        self.assertEqual(len(data["similar_groups"]), 1)
        self.assertEqual(set(data["similar_groups"][0]["asset_ids"]), {"asset_inn_1", "asset_inn_2", "asset_inn_3"})
        selections = {asset["asset_id"]: asset["similar_selection"] for asset in data["assets"]}
        self.assertEqual(selections["asset_inn_2"], "primary")
        self.assertEqual(selections["asset_inn_1"], "rejected")
        self.assertEqual(selections["asset_inn_3"], "rejected")
        self.assertEqual(selections["asset_road"], "none")

    def test_note_block_replacement_preserves_user_note(self):
        existing = "用户自己的备注\n<!-- TripClipper:start -->old<!-- TripClipper:end -->\n保留这段"
        updated = replace_managed_note_block(existing, "<!-- TripClipper:start -->new<!-- TripClipper:end -->")
        self.assertIn("用户自己的备注", updated)
        self.assertIn("new", updated)
        self.assertIn("保留这段", updated)
        self.assertNotIn("old", updated)

    def test_model_result_validation_rejects_bad_enum(self):
        with self.assertRaises(ModelProviderError):
            validate_analysis_result(
                {
                    "summary": "x",
                    "tags": [],
                    "rating": 5,
                    "subject_type": "bad",
                    "primary_subject": "x",
                    "people_presence": "none",
                    "shot_scale": "wide",
                    "shot_function": "highlight",
                    "segments": [],
                }
            )


if __name__ == "__main__":
    unittest.main()
