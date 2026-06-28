"""M3 CLI 集成测试（Task 9：SubTask 9.1-9.5）—— 真打 cherryin 上的
``google/gemini-3.5-flash``，零 mock。

测试纪律（同 :mod:`tests.test_integration_m3`）：

- 缺 ``TRIPCLIPPER_MODEL_API_KEY`` → 直接 ``pytest.fail``。
- 缺 ``tests/videos/<filename>`` → 直接 ``pytest.fail``。
- **不**使用 ``pytest.skipif`` / 不录制 / 不进 CI。
- 通过 :class:`click.testing.CliRunner` 真起 ``tripclipper`` 子命令，**不**绕过
  模型。为控成本，每个用例使用单视频（``DJI_20260612134026_0001_D.MP4``）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner
from dotenv import load_dotenv

from tripclipper.cli import main
from tripclipper.cut_index import read_cut_index
from tripclipper.models import AnalysisStatus
from tripclipper.paths import cut_index_path
from tripclipper.project import init_project
from tripclipper.scan import scan_project


VIDEOS_DIR = Path(__file__).resolve().parent / "videos"
SMALL_VIDEO = VIDEOS_DIR / "DJI_20260612134026_0001_D.MP4"

_PROVIDER_BASE_URL = "https://open.cherryin.ai/v1"
_VISION_MODEL = "google/gemini-3.5-flash"
_API_KEY_ENV = "TRIPCLIPPER_MODEL_API_KEY"

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env", override=False)


def _require_api_key() -> None:
    if not os.environ.get(_API_KEY_ENV, ""):
        pytest.fail(
            f"M3 CLI 集成测试需要 .env 配置 {_API_KEY_ENV}"
        )


def _require_video() -> Path:
    if not SMALL_VIDEO.is_file():
        pytest.fail(f"M3 CLI 集成测试需要 {SMALL_VIDEO} 存在")
    return SMALL_VIDEO


def _project_yaml(source_folder: Path) -> str:
    return (
        f'project_name: "M3 CLI Integration"\n'
        f'source_folder: "{source_folder}"\n'
        'output_style: "activity_recap"\n'
        'target_length: "3min"\n'
        "model_config:\n"
        '  provider: "openai_compatible"\n'
        f'  base_url: "{_PROVIDER_BASE_URL}"\n'
        f'  api_key_env: "{_API_KEY_ENV}"\n'
        f'  vision_model: "{_VISION_MODEL}"\n'
        f'  text_model: "{_VISION_MODEL}"\n'
        '  language: "zh-CN"\n'
        '  sample_size: 5\n'
    )


def _setup_scanned_project(tmp_path: Path) -> tuple[Path, str]:
    """在 ``tmp_path`` 下 symlink 一个真实视频并跑 init + scan，返回 ``(base_dir, slug)``。"""
    video = _require_video()
    source = tmp_path / "src"
    source.mkdir()
    (source / video.name).symlink_to(video)

    config_path = tmp_path / "project.yaml"
    config_path.write_text(_project_yaml(source), encoding="utf-8")
    base_dir = tmp_path / "projects"
    summary = init_project(config_path, base_dir=base_dir)
    scan_project(summary.project_slug, base_dir=base_dir)
    return base_dir, summary.project_slug


# ---------------------------------------------------------------------------
# SubTask 9.1：CliRunner 真起 analyze --stage sample，断言 stdout 与 cut_index
# ---------------------------------------------------------------------------


def test_cli_analyze_sample_real_model(tmp_path: Path):
    _require_api_key()
    base_dir, slug = _setup_scanned_project(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "analyze",
            slug,
            "--stage",
            "sample",
            "--base-dir",
            str(base_dir),
            "--concurrency",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "分析完成" in result.output
    assert "成功 N" in result.output
    assert "失败 M" in result.output
    assert "跳过 K" in result.output

    cut = read_cut_index(cut_index_path(slug, base_dir))
    assert cut.analysis is not None
    assert cut.analysis.stage == "sample"
    assert cut.analysis.status in {"completed", "partial"}
    analyzed = [a for a in cut.assets if a.analysis_status == AnalysisStatus.analyzed]
    assert len(analyzed) >= 1


# ---------------------------------------------------------------------------
# SubTask 9.2：未初始化项目（无 cut_index.json）跑 analyze --stage sample
# ---------------------------------------------------------------------------


def test_cli_analyze_sample_without_init_exits_nonzero(tmp_path: Path):
    # 不调任何模型；纯 CLI 硬卡路径。
    base_dir = tmp_path / "projects"
    base_dir.mkdir(parents=True, exist_ok=True)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "analyze",
            "nonexistent-slug",
            "--stage",
            "sample",
            "--base-dir",
            str(base_dir),
        ],
    )
    assert result.exit_code != 0
    # stderr 与 stdout 在 CliRunner 默认 mix_stderr=True 下合并到 output。
    assert "尚未初始化" in result.output or "未找到" in result.output
    # 不应抛裸堆栈
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# SubTask 9.3：scanned 素材为零（只 init 未 scan）—— 退出码非 0、清晰提示
# ---------------------------------------------------------------------------


def test_cli_analyze_sample_without_scan_exits_nonzero(tmp_path: Path):
    # init 但不 scan —— cut_index 存在但 assets 为空。
    source = tmp_path / "src"
    source.mkdir()
    # 放一个真实视频但故意不 scan
    video = _require_video()
    (source / video.name).symlink_to(video)

    config_path = tmp_path / "project.yaml"
    config_path.write_text(_project_yaml(source), encoding="utf-8")
    base_dir = tmp_path / "projects"
    summary = init_project(config_path, base_dir=base_dir)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "analyze",
            summary.project_slug,
            "--stage",
            "sample",
            "--base-dir",
            str(base_dir),
        ],
    )
    assert result.exit_code != 0
    assert "没有可分析的 asset" in result.output or "先运行" in result.output
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# SubTask 9.4：full --force 全量 / 不带 --force 跳过已 analyzed
# ---------------------------------------------------------------------------


def test_cli_analyze_full_skip_and_force(tmp_path: Path):
    """先跑 sample 把 1 个素材打成 analyzed，再分两次跑 full：

    - 不带 ``--force``：``skipped >= 1``，stdout 含「跳过 N 个已完成素材」。
    - 带 ``--force``：跳过为 0，stdout **不**含「跳过 N 个已完成素材」。

    两次 full 各真打模型一次（force=False 不会真调，因为唯一素材被跳过；
    force=True 会真调一次）。
    """
    _require_api_key()
    base_dir, slug = _setup_scanned_project(tmp_path)

    runner = CliRunner()

    # Step 1: sample —— 真打一次，让唯一素材进 analyzed。
    sample_res = runner.invoke(
        main,
        [
            "analyze",
            slug,
            "--stage",
            "sample",
            "--base-dir",
            str(base_dir),
            "--concurrency",
            "1",
        ],
    )
    assert sample_res.exit_code == 0, sample_res.output

    cut_after_sample = read_cut_index(cut_index_path(slug, base_dir))
    assert any(
        a.analysis_status == AnalysisStatus.analyzed for a in cut_after_sample.assets
    ), "sample 阶段应至少把 1 个素材打成 analyzed"

    # Step 2: full 不带 --force —— 应跳过已 analyzed 的素材。
    full_no_force = runner.invoke(
        main,
        [
            "analyze",
            slug,
            "--stage",
            "full",
            "--base-dir",
            str(base_dir),
            "--concurrency",
            "1",
        ],
    )
    assert full_no_force.exit_code == 0, full_no_force.output
    assert "跳过" in full_no_force.output
    assert "已完成素材" in full_no_force.output

    # Step 3: full --force —— 强制重分析，真打一次。
    full_force = runner.invoke(
        main,
        [
            "analyze",
            slug,
            "--stage",
            "full",
            "--force",
            "--base-dir",
            str(base_dir),
            "--concurrency",
            "1",
        ],
    )
    assert full_force.exit_code == 0, full_force.output
    # --force 下不再走"跳过 N 个已完成素材"这条 stdout 分支
    assert "跳过 1 个已完成素材" not in full_force.output


# ---------------------------------------------------------------------------
# SubTask 9.5：run --pause-after sample，CliRunner 注入回车继续 full
# ---------------------------------------------------------------------------


def test_cli_run_pause_after_sample(tmp_path: Path):
    """``tripclipper run <slug> --pause-after sample`` 真打一次 scan/sample/full。

    单视频跑 scan + sample + full，``--pause-after sample`` 后会用
    ``input()`` 阻塞，向 CliRunner 注入 ``"\\n"`` 让其继续。
    """
    _require_api_key()
    base_dir, slug = _setup_scanned_project(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "run",
            slug,
            "--base-dir",
            str(base_dir),
            "--pause-after",
            "sample",
            "--concurrency",
            "1",
        ],
        input="\n",
    )
    assert result.exit_code == 0, result.output
    assert "run 完成" in result.output
    assert "[scan]" in result.output
    assert "[sample]" in result.output
    assert "[full]" in result.output

    cut = read_cut_index(cut_index_path(slug, base_dir))
    assert cut.analysis is not None
    # 最后一阶段是 full，AnalysisInfo 应该被 full_analyze 覆盖。
    assert cut.analysis.stage == "full"
