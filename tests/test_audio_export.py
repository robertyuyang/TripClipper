from __future__ import annotations

import csv
import json
from pathlib import Path

from tripclipper.cut_index import write_cut_index
from tripclipper.exporter import render_assets_csv, render_review_html
from tripclipper.models import (
    Asset,
    CutIndex,
    ProjectInfo,
    SpeechQuality,
)
from tripclipper.paths import cut_index_path


def _project(tmp_path: Path) -> tuple[str, Path]:
    slug = "audio-review"
    cut = CutIndex(
        project=ProjectInfo(project_name="音频验收", project_slug=slug),
        assets=[
            Asset(
                asset_id="clear1",
                filename="clear.mp4",
                speech_quality=SpeechQuality.clear,
                transcript_path="cache/transcripts/clear1.json",
            ),
            Asset(
                asset_id="broken1",
                filename="broken.mp4",
                speech_quality=SpeechQuality.unclear,
                transcript_path="cache/transcripts/broken1.json",
            ),
            Asset(asset_id="pending1", filename="pending.mp4"),
        ],
    )
    write_cut_index(cut_index_path(slug, tmp_path), cut)
    transcript = tmp_path / slug / "cache" / "transcripts" / "clear1.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps(
            {
                "speech_quality": "clear",
                "speech_segments": [
                    {"start_sec": 12.4, "end_sec": 18.9, "text": "我们到达山顶"}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return slug, transcript


def test_assets_csv_contains_speech_quality(tmp_path: Path) -> None:
    slug, _ = _project(tmp_path)
    path = render_assets_csv(slug, base_dir=tmp_path)
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["speech_quality"] == "clear"
    assert rows[1]["speech_quality"] == "unclear"
    assert rows[2]["speech_quality"] == ""


def test_review_displays_quality_segments_and_local_degradation(tmp_path: Path) -> None:
    slug, _ = _project(tmp_path)
    html = render_review_html(slug, base_dir=tmp_path).read_text(encoding="utf-8")
    assert "speech_quality" in html
    assert "clear" in html
    assert "12.4–18.9 秒" in html
    assert "我们到达山顶" in html
    assert "转写文件不可用" in html
    assert "pending.mp4" in html
