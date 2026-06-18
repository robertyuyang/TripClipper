from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tripclipper.analyzer import analyze_project
from tripclipper.config import create_project_config, load_project_config
from tripclipper.eagle import eagle_dry_run, replace_managed_note_block
from tripclipper.exporter import export_project
from tripclipper.index import load_index
from tripclipper.model_provider import ModelProvider, ModelProviderError, validate_analysis_result


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
            self.assertEqual(config.source_folder, source.resolve())

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
