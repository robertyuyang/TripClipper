"""M3/M4 CLI 集成测试（Task 9 SubTask 9.1-9.5；M4 Task 10 SubTask 10.1-10.5）。

M3 部分（``test_cli_analyze_*`` / ``test_cli_run_pause_after_sample``）真打
cherryin 上的 ``google/gemini-3.5-flash``，零 mock。

M4 部分（``test_cli_analyze_cluster_*`` / ``test_cli_run_includes_cluster_summary``）
聚焦 CLI 接线（错误兜底 + warning 走向 + summary 行）：

- 部分用例真打模型（10.5：``run`` 端到端单视频，sample 真打、cluster 因
  ``total_groups == 0`` 不进入 Arbiter 真调）；
- 部分用例用 ``monkeypatch`` 替换 ``cluster_runner.Arbiter`` 为
  ``_FakeArbiter`` 测试替身（10.1/10.4）。FakeArbiter 仅用于让 cluster_runner
  的编排能在不真打 LLM 的前提下走通 CLI 入口的 stdout/stderr 路径——它的
  存在与"M4 真模型决策正确性"正交（那部分由
  ``tests/test_integration_m4.py`` 真打覆盖）。

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

from tripclipper import cluster_runner as _cluster_runner_module
from tripclipper.arbiter import ArbitrationResult
from tripclipper.cli import main
from tripclipper.cut_index import read_cut_index, write_cut_index
from tripclipper.models import (
    AnalysisInfo,
    AnalysisStatus,
    Asset,
    CutIndex,
    ProjectInfo,
    SubjectType,
)
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
        "analysis_config:\n"
        '  sample_size: 5\n'
        '  language: "zh-CN"\n'
        "model_config:\n"
        '  provider: "openai_compatible"\n'
        f'  base_url: "{_PROVIDER_BASE_URL}"\n'
        f'  api_key_env: "{_API_KEY_ENV}"\n'
        f'  vision_model: "{_VISION_MODEL}"\n'
        f'  text_model: "{_VISION_MODEL}"\n'
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


# ---------------------------------------------------------------------------
# M4 Task 10：cluster CLI 接线
# ---------------------------------------------------------------------------
#
# 设计说明：
#
# - 10.1 / 10.4 / 10.5 中 cluster 阶段的"真模型决策"由
#   ``tests/test_integration_m4.py``（Task 9）真打覆盖；本文件聚焦 CLI 接线，
#   即 stdout/stderr 文案、退出码、cut_index 终态字段。在 Arbiter 真调成本
#   高、用例又多的情况下，10.1 / 10.4 用 monkeypatch 替换
#   ``cluster_runner.Arbiter`` 为 ``_FakeArbiter`` 测试替身。
# - ``_FakeArbiter`` 不是模型 mock：它返回的 :class:`ArbitrationResult` 是
#   测试自己定义的、与"模型决策正确性"正交。
# - 10.2 / 10.3 不进入仲裁，连 FakeArbiter 都不需要——只测前置硬卡的 stderr
#   走向。
# - 10.5 用真打 sample/full（与 9.5 同款单视频），cluster 阶段因为单视频
#   不构成相似组，``total_groups == 0`` 时 Arbiter 不被调用，因此**不需要**
#   FakeArbiter，也不会真打仲裁 API。


class _FakeArbiterTrivial:
    """编排测试替身：不做任何模型调用；``arbitrate`` 返回简单合法的
    :class:`ArbitrationResult`。

    用法：``monkeypatch.setattr(cluster_runner, "Arbiter", _FakeArbiterTrivial)``。
    存在意义：让 ``cluster_runner.cluster`` 走完整流程（探测 + 头/尾落盘 + 候选
    池构建），但不真打 LLM；与"M4 真模型决策正确性"正交（那部分由
    ``tests/test_integration_m4.py`` 真打覆盖）。
    """

    def __init__(self, config, editing_intent):  # noqa: D401, ANN001
        self.config = config
        self.editing_intent = editing_intent

    def arbitrate(self, group_assets):
        ids = [a.asset_id for a in group_assets if a.asset_id]
        return ArbitrationResult(
            primary_asset_id=ids[0] if ids else None,
            alternate_asset_ids=ids[1:],
            rejected_asset_ids=[],
            confidence=0.9,
            basis=["相近构图"],
            reason_by_asset={aid: "测试替身理由" for aid in ids},
            needs_review=False,
        )


def _seed_analyzed_cut_index(
    tmp_path: Path,
    *,
    analysis_stage: str = "full",
    analysis_status: str = "completed",
) -> tuple[Path, str]:
    """在 ``tmp_path`` 下构造一个最小可用项目：``project.yaml`` +
    ``cut_index.json`` 含 3 条 ``analyzed`` 强信号轨素材（building）。

    返回 ``(base_dir, slug)``。``analysis`` 字段按参数控制 stage / status
    （用于 10.1 / 10.4 不同前置）。**完全不真打模型**——3 条 asset 是手工合成
    的"分析后状态"，但本测试不会读它们的 ``summary``/``tags`` 等"模型分析
    结果"字段做断言；它们只用来让 ``cluster_candidates`` 形成 1 个候选组，
    使 ``cluster_runner`` 端到端跑通。
    """
    slug = "demo"
    base_dir = tmp_path / "projects"
    project_dir = base_dir / slug
    project_dir.mkdir(parents=True)

    yaml_path = project_dir / "project.yaml"
    yaml_path.write_text(
        # source_folder 用 project_dir 自身（已存在）满足 load_config 校验。
        f'project_name: "demo"\n'
        f'source_folder: "{project_dir}"\n'
        "model_config:\n"
        '  provider: "openai_compatible"\n'
        f'  base_url: "{_PROVIDER_BASE_URL}"\n'
        f'  api_key_env: "{_API_KEY_ENV}"\n'
        f'  vision_model: "{_VISION_MODEL}"\n'
        '  language: "zh-CN"\n',
        encoding="utf-8",
    )

    project = ProjectInfo(
        project_name="demo",
        project_slug=slug,
        config_path=str(yaml_path),
    )
    analysis = AnalysisInfo(stage=analysis_stage, status=analysis_status)
    assets = [
        Asset(
            asset_id="a1",
            relative_path="a1.mp4",
            analysis_status=AnalysisStatus.analyzed,
            modified_time="2025-06-12T11:41:46+00:00",
            subject_type=SubjectType.building,
            rating=5,
            metadata={},
        ),
        Asset(
            asset_id="a2",
            relative_path="a2.mp4",
            analysis_status=AnalysisStatus.analyzed,
            modified_time="2025-06-12T11:41:56+00:00",
            subject_type=SubjectType.building,
            rating=4,
            metadata={},
        ),
        Asset(
            asset_id="a3",
            relative_path="a3.mp4",
            analysis_status=AnalysisStatus.analyzed,
            modified_time="2025-06-12T11:42:06+00:00",
            subject_type=SubjectType.building,
            rating=3,
            metadata={},
        ),
    ]
    cut = CutIndex(project=project, analysis=analysis, assets=assets)
    write_cut_index(project_dir / "cut_index.json", cut)
    # 注入一个空的 api_key_env 也行——_FakeArbiter 不读它，但 Arbiter 真实
    # 构造路径在 10.1/10.4 中被 monkeypatch 替换；这里不用关心 env。
    return base_dir, slug


# ---------------------------------------------------------------------------
# SubTask 10.1：analyze --stage cluster 成功路径（FakeArbiter，编排端到端）
# ---------------------------------------------------------------------------


def test_cli_analyze_cluster_success_writes_terminal_status(
    tmp_path: Path, monkeypatch
):
    """``tripclipper analyze <slug> --stage cluster`` 成功路径：

    - 退出码 0；
    - stdout 含"聚类完成（cluster）"摘要（CLI 模板）；
    - ``cut_index.json`` 已写 ``clustering.status`` 终态
      （``completed`` / ``partial`` / ``failed``）。

    Arbiter 被替换为 :class:`_FakeArbiterTrivial`，不真打 LLM——真模型决策
    正确性由 ``tests/test_integration_m4.py``（Task 9）覆盖。
    """
    base_dir, slug = _seed_analyzed_cut_index(tmp_path)

    monkeypatch.setattr(_cluster_runner_module, "Arbiter", _FakeArbiterTrivial)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "analyze",
            slug,
            "--stage",
            "cluster",
            "--base-dir",
            str(base_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "聚类完成" in result.output or "cluster" in result.output
    assert "组总数" in result.output
    assert "Traceback" not in result.output

    cut = read_cut_index(cut_index_path(slug, base_dir))
    assert cut.clustering is not None
    assert cut.clustering.status in {"completed", "partial", "failed"}


# ---------------------------------------------------------------------------
# SubTask 10.2：未 init 项目跑 analyze --stage cluster
# ---------------------------------------------------------------------------


def test_cli_analyze_cluster_without_init_exits_nonzero(tmp_path: Path):
    """无 ``cut_index.json`` 时 cluster 应硬卡：

    - 退出码非 0；
    - stderr 含友好提示（提到 init / scan / analyze）；
    - 不抛裸堆栈。
    """
    base_dir = tmp_path / "projects"
    base_dir.mkdir(parents=True, exist_ok=True)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "analyze",
            "nonexistent-slug",
            "--stage",
            "cluster",
            "--base-dir",
            str(base_dir),
        ],
    )
    assert result.exit_code != 0
    # cluster_runner.cluster 抛 ClusterRunnerError，CLI 翻译为"聚类失败：…"前缀。
    assert "聚类失败" in result.output
    # 友好提示应引导用户先 init / analyze --stage scan。
    assert (
        "尚未初始化" in result.output
        or "未找到" in result.output
        or "tripclipper init" in result.output
    )
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# SubTask 10.3：已 init 但未跑 analyze --stage full
# ---------------------------------------------------------------------------


def test_cli_analyze_cluster_without_full_analysis_exits_nonzero(tmp_path: Path):
    """``analysis`` 缺失或非 ``completed``/``partial`` 时 cluster 应硬卡：

    - 退出码非 0；
    - stderr 提示先跑 ``tripclipper analyze --stage full``；
    - 不抛裸堆栈。

    用 init + scan 流程（不调任何 LLM），让 ``cut_index.json`` 存在但
    ``analysis.status`` 不是 ``completed``——这等价于 spec 10.3 要求的"已 init+scan
    但未 analyze"前置。
    """
    video = _require_video()
    source = tmp_path / "src"
    source.mkdir()
    (source / video.name).symlink_to(video)

    config_path = tmp_path / "project.yaml"
    config_path.write_text(_project_yaml(source), encoding="utf-8")
    base_dir = tmp_path / "projects"
    summary = init_project(config_path, base_dir=base_dir)
    scan_project(summary.project_slug, base_dir=base_dir)

    # 未跑 analyze --stage full —— cut.analysis.status 应不是 completed。
    cut_before = read_cut_index(cut_index_path(summary.project_slug, base_dir))
    assert cut_before.analysis is None or cut_before.analysis.status not in {
        "completed",
        "partial",
    }

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "analyze",
            summary.project_slug,
            "--stage",
            "cluster",
            "--base-dir",
            str(base_dir),
        ],
    )
    assert result.exit_code != 0
    assert "聚类失败" in result.output
    # 友好提示应引导用户先跑 analyze --stage full。
    assert "analyze" in result.output and "full" in result.output
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# SubTask 10.4：analysis.stage == "sample" 时 cluster 仍可跑，但带 stderr warning
# ---------------------------------------------------------------------------


def test_cli_analyze_cluster_sample_only_emits_warning(
    tmp_path: Path, monkeypatch
):
    """``analysis.stage == "sample"`` 且 ``status == "completed"`` 时 cluster
    应继续，但向 stderr 打 warning：

    - 退出码 0；
    - stderr 含 ``"警告：仅基于 sample 阶段"``；
    - stdout 含聚类完成摘要。

    Arbiter 被替换为 :class:`_FakeArbiterTrivial`，不真打 LLM。
    """
    base_dir, slug = _seed_analyzed_cut_index(
        tmp_path, analysis_stage="sample", analysis_status="completed"
    )

    monkeypatch.setattr(_cluster_runner_module, "Arbiter", _FakeArbiterTrivial)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "analyze",
            slug,
            "--stage",
            "cluster",
            "--base-dir",
            str(base_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    # warning 走 sys.stderr.write，被 CliRunner 捕获到 result.stderr 与
    # result.output（合并视图）；这里在 stderr 上断言更精确。
    assert "警告：仅基于 sample 阶段" in result.stderr
    assert "聚类完成" in result.output
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# SubTask 10.5：tripclipper run 摘要含 [cluster] 行
# ---------------------------------------------------------------------------


def test_cli_run_includes_cluster_summary(tmp_path: Path):
    """``tripclipper run <slug>`` 在 scan/sample/full 走完后会自动跑 cluster
    一次。CLI 摘要应包含 ``[cluster]`` 一行。

    与 9.5 同款：单视频 + 真打 sample/full。cluster 阶段对单视频仅形成 0
    个候选组（``cluster_candidates`` 至少需要 2 个素材才能配对），因此
    Arbiter 真实构造但 ``arbitrate`` 不会被调用——也就**不会**真打仲裁
    API。这里的真打仅限于 M3 sample/full 已有覆盖范围。
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
            "--concurrency",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "run 完成" in result.output
    assert "[scan]" in result.output
    assert "[sample]" in result.output
    assert "[full]" in result.output
    # 关键断言：cluster 摘要行存在。
    assert "[cluster]" in result.output

    cut = read_cut_index(cut_index_path(slug, base_dir))
    assert cut.clustering is not None
    assert cut.clustering.status in {"completed", "partial", "failed"}
