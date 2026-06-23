from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tripclipper.config import create_project_config, load_project_config
from tripclipper.scanner import build_asset_record, generate_video_frames


class ScannerFrameTests(unittest.TestCase):
    def test_generate_video_frames_samples_representative_offsets(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "clip.mp4"
            video.write_bytes(b"video")
            project_dir = Path(tmp) / "project"

            def fake_run(command, **kwargs):
                Path(command[-1]).write_bytes(b"jpg")
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch("tripclipper.scanner.subprocess.run", side_effect=fake_run) as run:
                frames = generate_video_frames(video, project_dir, "asset_123", 10.0)

            self.assertEqual(
                [path.name for path in frames],
                ["asset_123_early.jpg", "asset_123_middle.jpg", "asset_123_late.jpg"],
            )
            self.assertEqual([call.args[0][3] for call in run.call_args_list], ["2.000", "5.000", "8.000"])

    def test_video_thumbnail_uses_middle_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "media"
            source.mkdir()
            video = source / "clip.mp4"
            video.write_bytes(b"video")
            config_path = create_project_config(
                {"project_name": "Frames", "source_folder": str(source)},
                base_dir=tmp,
            )
            config = load_project_config(config_path)
            frames = [
                config.project_dir / "early.jpg",
                config.project_dir / "middle.jpg",
                config.project_dir / "late.jpg",
            ]

            with mock.patch(
                "tripclipper.scanner.ffprobe_metadata",
                return_value=({"duration_seconds": 10.0}, None),
            ):
                with mock.patch("tripclipper.scanner.generate_video_frames", return_value=frames):
                    asset = build_asset_record(video.resolve(), config, {"ffprobe": True, "ffmpeg": True})

            self.assertEqual(asset["frame_paths"], [str(frame) for frame in frames])
            self.assertEqual(asset["thumbnail_path"], str(frames[1]))


if __name__ == "__main__":
    unittest.main()
