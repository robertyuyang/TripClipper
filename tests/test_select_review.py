from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

import pytest
from click.testing import CliRunner

from tripclipper.clip_selection.review import render_selection_review
from tripclipper.cli import main
from tripclipper.paths import selection_review_html_path


@pytest.fixture
def review_task(tmp_path: Path) -> dict[str, Path]:
    base_dir = tmp_path / "projects"
    project_dir = base_dir / "demo"
    task_dir = project_dir / "selections" / "快剪"
    source_dir = tmp_path / "素材 & source"
    source_dir.mkdir(parents=True)
    task_dir.mkdir(parents=True)

    (source_dir / "people <one>.mp4").write_bytes(b"video")
    (source_dir / "still.jpg").write_bytes(b"image")
    (task_dir / "brief.md").write_text(
        "# 快剪 <验收>\n\n剪一个 30 秒视频。 </script><script>alert(1)</script>",
        encoding="utf-8",
    )
    state_path = task_dir / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "task_name": "快剪",
                "status": "completed",
                "target_duration_sec": 30,
                "categories": [
                    {
                        "category_id": "category-001",
                        "name": "人物 <高能>",
                        "required": True,
                        "purpose": "用于开头 & 高潮",
                        "missing_reason": None,
                    },
                    {
                        "category_id": "category-002",
                        "name": "环境空镜",
                        "required": True,
                        "purpose": "用于过渡",
                        "missing_reason": None,
                    },
                ],
                "asset_progress": {
                    "listed_pages": [1, 2],
                    "opened_asset_ids": ["asset-video"],
                },
                "candidates": [
                    {
                        "candidate_id": "candidate-001",
                        "asset_id": "asset-video",
                        "start_sec": 2,
                        "end_sec": 20,
                        "status": "primary",
                        "category_ids": ["category-001", "category-002"],
                        "recommended_use": "开头 & 高潮",
                        "reason": "人物 <表情> 自然 </script>",
                    },
                    {
                        "candidate_id": "candidate-002",
                        "asset_id": "asset-video",
                        "start_sec": 10,
                        "end_sec": 25,
                        "status": "primary",
                        "category_ids": ["category-002"],
                        "recommended_use": None,
                        "reason": "与上一段重叠",
                    },
                    {
                        "candidate_id": "candidate-003",
                        "asset_id": "asset-image",
                        "start_sec": 0,
                        "end_sec": 3,
                        "status": "primary",
                        "category_ids": [],
                        "recommended_use": "静态过渡",
                        "reason": "图片不能区间播放",
                    },
                    {
                        "candidate_id": "candidate-004",
                        "asset_id": "asset-missing",
                        "start_sec": 0,
                        "end_sec": 2,
                        "status": "primary",
                        "category_ids": [],
                        "recommended_use": None,
                        "reason": "索引缺失",
                    },
                    {
                        "candidate_id": "candidate-005",
                        "asset_id": "asset-video",
                        "start_sec": 28,
                        "end_sec": 35,
                        "status": "primary",
                        "category_ids": [],
                        "recommended_use": None,
                        "reason": "时间越界",
                    },
                    {
                        "candidate_id": "candidate-006",
                        "asset_id": "asset-no-file",
                        "start_sec": 0,
                        "end_sec": 5,
                        "status": "primary",
                        "category_ids": [],
                        "recommended_use": None,
                        "reason": "文件不存在",
                    },
                ],
                "unresolved": [{"priority": "high", "message": "需确认节奏"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    events_path = task_dir / "events.jsonl"
    events_path.write_text('{"event_type":"selection_completed"}\n', encoding="utf-8")
    cut_index_path = project_dir / "cut_index.json"
    cut_index_path.write_text(
        json.dumps(
            {
                "schema_version": "0.4",
                "project": {
                    "project_slug": "demo",
                    "project_name": "演示项目",
                    "source_folder": str(source_dir),
                },
                "assets": [
                    {
                        "asset_id": "asset-video",
                        "filename": "people <one>.mp4",
                        "relative_path": "people <one>.mp4",
                        "type": "video",
                        "metadata": {"duration": 30.0},
                    },
                    {
                        "asset_id": "asset-image",
                        "filename": "still.jpg",
                        "relative_path": "still.jpg",
                        "type": "image",
                        "metadata": {},
                    },
                    {
                        "asset_id": "asset-no-file",
                        "filename": "gone.mp4",
                        "relative_path": "gone.mp4",
                        "type": "video",
                        "metadata": {"duration": 10.0},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {
        "base_dir": base_dir,
        "task_dir": task_dir,
        "state_path": state_path,
        "events_path": events_path,
        "brief_path": task_dir / "brief.md",
        "cut_index_path": cut_index_path,
        "source_dir": source_dir,
    }


def _hashes(paths: list[Path]) -> dict[Path, str]:
    return {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def _review_data(html: str) -> dict:
    match = re.search(
        r'<script id="review-data" type="application/json">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1).replace("<\\/", "</"))


def test_selection_review_path_is_inside_task_directory(tmp_path: Path) -> None:
    assert selection_review_html_path("demo", "快剪", tmp_path) == (
        tmp_path / "demo" / "selections" / "快剪" / "select-review.html"
    )


def test_render_review_joins_assets_and_preserves_candidate_order(
    review_task: dict[str, Path],
) -> None:
    output = render_selection_review(
        "demo",
        "快剪",
        base_dir=review_task["base_dir"],
    )
    html = output.read_text(encoding="utf-8")

    assert output == (review_task["task_dir"] / "select-review.html").resolve()
    assert html.index("candidate-001") < html.index("candidate-002")
    assert "people &lt;one&gt;.mp4" in html
    assert (review_task["source_dir"] / "people <one>.mp4").resolve().as_uri() in html
    assert "40 秒" in html
    assert "2/2" in html
    assert "1/3" in html


def test_render_review_escapes_text_and_script_terminator(
    review_task: dict[str, Path],
) -> None:
    html = render_selection_review(
        "demo",
        "快剪",
        base_dir=review_task["base_dir"],
    ).read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "人物 &lt;高能&gt;" in html
    assert "开头 &amp; 高潮" in html
    assert "<\\/script>" in html


def test_render_review_marks_missing_non_video_and_invalid_ranges(
    review_task: dict[str, Path],
) -> None:
    html = render_selection_review(
        "demo",
        "快剪",
        base_dir=review_task["base_dir"],
    ).read_text(encoding="utf-8")

    assert "非视频素材" in html
    assert "素材索引不存在" in html
    assert "时间范围错误" in html
    assert "源文件不可访问" in html


def test_video_without_index_duration_is_checked_by_browser_metadata(
    review_task: dict[str, Path],
) -> None:
    cut = json.loads(review_task["cut_index_path"].read_text(encoding="utf-8"))
    cut["assets"][0]["metadata"] = {}
    review_task["cut_index_path"].write_text(
        json.dumps(cut, ensure_ascii=False),
        encoding="utf-8",
    )

    html = render_selection_review(
        "demo",
        "快剪",
        base_dir=review_task["base_dir"],
    ).read_text(encoding="utf-8")

    first = _review_data(html)["candidates"][0]
    assert first["canPlay"] is True
    assert first["issue"] is None


def test_render_review_preserves_all_input_hashes(
    review_task: dict[str, Path],
) -> None:
    inputs = [
        review_task["cut_index_path"],
        review_task["state_path"],
        review_task["brief_path"],
        review_task["events_path"],
    ]
    before = _hashes(inputs)

    render_selection_review("demo", "快剪", base_dir=review_task["base_dir"])
    render_selection_review("demo", "快剪", base_dir=review_task["base_dir"])

    assert _hashes(inputs) == before


def test_primary_duration_merges_overlapping_ranges_per_asset(
    review_task: dict[str, Path],
) -> None:
    state = json.loads(review_task["state_path"].read_text(encoding="utf-8"))
    state["candidates"] = state["candidates"][:2]
    state["unresolved"] = []
    review_task["state_path"].write_text(
        json.dumps(state, ensure_ascii=False),
        encoding="utf-8",
    )

    html = render_selection_review(
        "demo",
        "快剪",
        base_dir=review_task["base_dir"],
    ).read_text(encoding="utf-8")

    assert "主选总时长<strong>23 秒</strong>" in html


def test_review_contains_single_player_and_read_only_controls(
    review_task: dict[str, Path],
) -> None:
    html = render_selection_review(
        "demo",
        "快剪",
        base_dir=review_task["base_dir"],
    ).read_text(encoding="utf-8")

    assert html.count('id="review-player"') == 1
    assert html.count('<button class="candidate-card"') == 6
    assert 'id="category-filters"' in html
    assert "function selectCandidate" in html
    assert "function replayCurrent" in html
    assert "function moveCurrent" in html
    assert "function clampToCandidateRange" in html
    assert 'addEventListener("timeupdate"' in html
    assert 'addEventListener("seeking"' in html
    assert 'addEventListener("error"' in html
    assert "不自动播放下一条" in html
    assert "fetch(" not in html
    assert "localStorage" not in html
    assert "indexedDB" not in html
    assert "autoplay" not in html.lower()

    move_body = re.search(
        r"function moveCurrent\([^)]*\)\s*\{(?P<body>.*?)\n\s*\}",
        html,
        flags=re.DOTALL,
    )
    assert move_body is not None
    assert ".play(" not in move_body.group("body")


def test_unresolved_items_use_warning_panel(review_task: dict[str, Path]) -> None:
    html = render_selection_review(
        "demo",
        "快剪",
        base_dir=review_task["base_dir"],
    ).read_text(encoding="utf-8")

    assert '<section class="panel warning" data-section="unresolved">' in html


def test_player_navigation_and_boundaries_run_in_scripted_dom(
    review_task: dict[str, Path],
) -> None:
    output = render_selection_review(
        "demo",
        "快剪",
        base_dir=review_task["base_dir"],
    )
    harness = Path(__file__).parent / "js" / "select_review_harness.mjs"

    result = subprocess.run(
        ["node", str(harness), str(output)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_select_review_cli_is_idempotent_and_preserves_inputs(
    monkeypatch,
    review_task: dict[str, Path],
) -> None:
    inputs = [
        review_task["cut_index_path"],
        review_task["state_path"],
        review_task["brief_path"],
        review_task["events_path"],
    ]
    before = _hashes(inputs)
    opened: list[str] = []
    def open_browser(uri: str) -> bool:
        opened.append(uri)
        return True

    monkeypatch.setattr("tripclipper.cli.webbrowser.open", open_browser)
    arguments = [
        "select-review",
        "demo",
        "快剪",
        "--base-dir",
        str(review_task["base_dir"]),
        "--open",
    ]

    first = CliRunner().invoke(main, arguments)
    first_html = (review_task["task_dir"] / "select-review.html").read_bytes()
    second = CliRunner().invoke(main, arguments)

    assert first.exit_code == second.exit_code == 0
    assert "审阅页面" in first.output
    assert opened == [
        (review_task["task_dir"] / "select-review.html").resolve().as_uri(),
        (review_task["task_dir"] / "select-review.html").resolve().as_uri(),
    ]
    assert (review_task["task_dir"] / "select-review.html").read_bytes() == first_html
    assert _hashes(inputs) == before


def test_select_review_cli_reports_missing_task(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main,
        ["select-review", "missing", "任务", "--base-dir", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Brief不存在" in result.output


def test_select_review_cli_fails_when_browser_does_not_open(
    monkeypatch,
    review_task: dict[str, Path],
) -> None:
    monkeypatch.setattr("tripclipper.cli.webbrowser.open", lambda uri: False)

    result = CliRunner().invoke(
        main,
        [
            "select-review",
            "demo",
            "快剪",
            "--base-dir",
            str(review_task["base_dir"]),
            "--open",
        ],
    )

    assert result.exit_code == 1
    assert "浏览器未能打开" in result.output
