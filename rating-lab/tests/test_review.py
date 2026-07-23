"""评分实验室人工复核测试。"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest


def test_single_highlight_prompt_encodes_rating_contract() -> None:
    prompt_path = Path(__file__).parents[1] / "prompts" / "single-highlight-v2.txt"
    prompt = prompt_path.read_text(encoding="utf-8")

    assert "素材总评分必须等于最佳片段的评分" in prompt
    assert "局部高光不得因为只占素材的一部分而降级" in prompt
    assert "4 星或 5 星" in prompt and "合法时间范围" in prompt
    assert "不考虑素材之间的独特性、重复性" in prompt
    assert "只有局部片段精彩，素材整体评为 3 星" not in prompt


def test_single_highlight_v3_prompt_adds_category_anchors() -> None:
    prompt = (
        Path(__file__).parents[1] / "prompts" / "single-highlight-v3.txt"
    ).read_text(encoding="utf-8")

    assert "视觉奇观型高光" in prompt
    assert "人物反应型高光" in prompt
    assert "不要求必须存在动作峰值" in prompt
    assert "平稳运镜本身不是 4 星证据" in prompt
    assert "普通环境交代、房间展示、远景活动" in prompt
    assert "最高 3 星" in prompt


def test_single_highlight_v4_prompt_separates_role_from_quality() -> None:
    prompt = (
        Path(__file__).parents[1] / "prompts" / "single-highlight-v4.txt"
    ).read_text(encoding="utf-8")

    assert "用途名称不决定评分上限" in prompt
    assert "即使最终作为过场或 B-roll 使用" in prompt
    assert "至少两个相互独立的视觉证据" in prompt
    assert "倾斜、旋转或移动本身不是降级理由" in prompt
    assert "真实人物状态" in prompt
    assert "普通房间展示" in prompt and "远景活动" in prompt


def test_write_manifest_refuses_to_replace_existing_sample(tmp_path: Path) -> None:
    from rating_lab.review import write_manifest

    path = tmp_path / "sample_manifest.json"
    manifest = {"schema_version": 1, "project_slug": "demo", "assets": []}

    write_manifest(path, manifest)

    assert json.loads(path.read_text(encoding="utf-8")) == manifest
    with pytest.raises(FileExistsError):
        write_manifest(path, manifest)


def test_write_manual_labels_omits_baseline_rating(tmp_path: Path) -> None:
    from rating_lab.review import write_manual_labels

    manifest = {
        "assets": [
            {
                "asset_id": "asset-1",
                "relative_path": "含,逗号/video.mp4",
                "baseline_rating": 4,
            }
        ]
    }
    path = tmp_path / "manual_labels.csv"

    write_manual_labels(path, manifest)

    text = path.read_text(encoding="utf-8")
    assert "baseline_rating" not in text
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "asset_id": "asset-1",
            "relative_path": "含,逗号/video.mp4",
            "expected_rating": "",
            "expected_action": "",
            "whole_asset_or_clip": "",
            "notes": "",
        }
    ]
    with pytest.raises(FileExistsError):
        write_manual_labels(path, manifest)


def test_write_manual_review_html_is_blind_and_escapes_paths(tmp_path: Path) -> None:
    from rating_lab.review import write_manual_review_html

    manifest = {
        "project_slug": "demo",
        "assets": [
            {
                "asset_id": "asset-1",
                "relative_path": 'day/<clip>&".mp4',
                "baseline_rating": 4,
            }
        ],
    }
    path = tmp_path / "manual-review.html"

    write_manual_review_html(path, manifest, "/素材")

    rendered = path.read_text(encoding="utf-8")
    assert "baseline_rating" not in rendered
    assert "旧评分" not in rendered
    assert '<video class="media"' in rendered
    assert "导出 CSV" in rendered
    assert "localStorage" in rendered
    assert "day/<clip>" not in rendered
    assert "expected_rating" in rendered
    with pytest.raises(FileExistsError):
        write_manual_review_html(path, manifest, "/素材")


def _read_prompt(name: str) -> str:
    return (Path(__file__).parents[1] / "prompts" / name).read_text(
        encoding="utf-8"
    )


def test_v5_prompts_share_non_negotiable_contract() -> None:
    prompts = [
        _read_prompt("single-highlight-v5-balanced.txt"),
        _read_prompt("single-highlight-v5-conservative.txt"),
        _read_prompt("single-highlight-v5-recall.txt"),
    ]

    for prompt in prompts:
        assert "素材总评分必须等于最佳片段的评分" in prompt
        assert "主体显著性" in prompt
        assert "持续且非叙事性的倾斜" in prompt
        assert "横竖方向本身不决定评分" in prompt
        assert "趣味动作" in prompt
        assert "少见运镜" in prompt
        assert "不得编造" in prompt


def test_v5_balanced_encodes_default_thresholds() -> None:
    prompt = _read_prompt("single-highlight-v5-balanced.txt")

    assert "实验室默认候选" in prompt
    assert "主体过小、处于边缘或构图意图不清时，最高 3 星" in prompt
    assert "内容意义不明、只能给出泛化用途时，最高 2 星" in prompt
    assert "一个足够强且清楚可见的证据" in prompt


def test_v5_conservative_requires_multiple_high_rating_evidence() -> None:
    prompt = _read_prompt("single-highlight-v5-conservative.txt")

    assert "至少两项相互独立的可见证据" in prompt
    assert "只有一个普通正向证据时，最高 3 星" in prompt
    assert "优先降低高分误判" in prompt


def test_v5_recall_accepts_one_strong_visible_highlight() -> None:
    prompt = _read_prompt("single-highlight-v5-recall.txt")

    assert "一个足够强且清楚可见的趣味细节" in prompt
    assert "局部高光不因占素材比例小而降级" in prompt
    assert "不放宽事实依据和时间范围要求" in prompt
