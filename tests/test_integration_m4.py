"""M4 Integration 测试（Task 9：SubTask 9.2 / 9.3）—— 真打 cherryin
``google/gemini-3.5-flash``，零 mock、零 skipif、缺 key 直接 fail。

测试纪律（spec Q1/Q2/Q17）：

- 缺 ``TRIPCLIPPER_MODEL_API_KEY`` → 直接 ``pytest.fail``。
- 缺 ``projects/demo-scan/`` 或 ``analysis.status != "completed"`` → 直接
  ``pytest.fail``。
- **不**使用 ``pytest.skipif`` / 不录制回放 / 不进 CI。
- 全部用例**原地**对 ``projects/demo-scan/`` 的 ``cut_index.json`` 读写——
  Setup 主动清空 cluster 相关字段；**不**做 teardown。允许跑完后直接打开
  ``cut_index.json`` 查看真实的 cluster 输出（spec 明确允许）。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from dotenv import load_dotenv

from tripclipper import cluster_runner
from tripclipper.cut_index import read_cut_index, write_cut_index
from tripclipper.models import EditCandidateStatus
from tripclipper.paths import cut_index_path, logs_dir


# ---------------------------------------------------------------------------
# 共享前置
# ---------------------------------------------------------------------------


_DEMO_SLUG = "demo-scan"
_API_KEY_ENV = "TRIPCLIPPER_MODEL_API_KEY"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEMO_BASE_DIR = _REPO_ROOT / "projects"

# 项目根的 .env 不一定已经被 pytest 进程加载——这里强制 load 一次（不覆盖已有 env）。
load_dotenv(_REPO_ROOT / ".env", override=False)


def _require_api_key() -> str:
    key = os.environ.get(_API_KEY_ENV, "")
    if not key:
        pytest.fail(
            "M4 集成测试需要 .env 配置 "
            f"{_API_KEY_ENV}（缺失或为空，且本仓库禁用 pytest.skipif）"
        )
    return key


def _require_demo_scan_completed():
    """``projects/demo-scan/`` 必须存在且 ``analysis.status='completed'`` 且 ``assets`` 非空。"""
    project_dir = _DEMO_BASE_DIR / _DEMO_SLUG
    if not project_dir.is_dir():
        pytest.fail(
            f"M4 集成测试需要 {project_dir} 存在；"
            "请先运行 `tripclipper run demo-scan` 把 analysis 跑完"
        )
    cut_path = cut_index_path(_DEMO_SLUG, _DEMO_BASE_DIR)
    if not cut_path.is_file():
        pytest.fail(f"M4 集成测试需要 {cut_path} 存在")
    cut = read_cut_index(cut_path)
    if cut.analysis is None or cut.analysis.status != "completed":
        status = cut.analysis.status if cut.analysis else None
        pytest.fail(
            f"M4 集成测试需要 demo-scan 的 analysis.status='completed'（当前 status={status}）"
        )
    if not cut.assets:
        pytest.fail("M4 集成测试需要 demo-scan 的 cut.assets 非空")


def _reset_cluster_state() -> None:
    """主动清空 cut.similar_groups / cut.default_candidates / cut.clustering 与
    每个 asset 的 similar_* / edit_candidate_* 字段，保留 analysis 与基础字段。
    """
    cut_path = cut_index_path(_DEMO_SLUG, _DEMO_BASE_DIR)
    cut = read_cut_index(cut_path)
    cut.similar_groups = []
    cut.default_candidates = []
    cut.clustering = None
    for asset in cut.assets:
        asset.similar_group_id = None
        asset.similar_selection = None
        asset.similar_rank = None
        asset.similar_reason = None
        asset.edit_candidate_status = None
        asset.edit_candidate_priority = None
        asset.edit_candidate_reason = None
    write_cut_index(cut_path, cut)


def _list_cluster_logs(min_mtime: float = 0.0) -> list[Path]:
    """列出 ``projects/demo-scan/logs/cluster-*.jsonl`` 中 mtime ≥ ``min_mtime`` 的文件。"""
    log_dir = logs_dir(_DEMO_SLUG, _DEMO_BASE_DIR)
    if not log_dir.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(log_dir.glob("cluster-*.jsonl")):
        if path.stat().st_mtime >= min_mtime:
            files.append(path)
    return files


# ---------------------------------------------------------------------------
# SubTask 9.2：端到端 cluster
# ---------------------------------------------------------------------------


def test_full_pipeline_with_cluster():
    """SubTask 9.2：原地对 demo-scan 跑一次 cluster，验证 cut_index 全字段就绪 + 日志落盘。

    Setup（同测试内）：清空 cut.similar_groups / cut.default_candidates / cut.clustering 与
    所有 asset 的 similar_*/edit_candidate_* 字段；落盘。
    Action：cluster_runner.cluster("demo-scan", base_dir=...)
    Teardown：**不还原**。允许跑完 pytest 后直接打开 cut_index.json 看真实输出
    （spec 明确允许）。下一次运行此用例时 Setup 会再清掉一次。
    """
    _require_api_key()
    _require_demo_scan_completed()
    _reset_cluster_state()

    cut_path = cut_index_path(_DEMO_SLUG, _DEMO_BASE_DIR)
    cut_before = read_cut_index(cut_path)
    # Setup 后置断言。
    assert cut_before.similar_groups == []
    assert cut_before.default_candidates == []
    assert cut_before.clustering is None
    assert cut_before.analysis.status == "completed"
    assert cut_before.assets

    test_start_mtime = time.time() - 1.0  # 留 1s 余量给 fs 时钟漂移
    result = cluster_runner.cluster(_DEMO_SLUG, base_dir=_DEMO_BASE_DIR)

    cut_after = read_cut_index(cut_path)

    # ---------- 断言：similar_groups ----------
    assert len(cut_after.similar_groups) >= 1, (
        "demo-scan 的连号样本应至少形成 1 个 SimilarGroup"
    )
    first_group = cut_after.similar_groups[0]
    if first_group.needs_review:
        # needs_review 时允许 primary_asset_id 为 None。
        assert first_group.primary_asset_id is None or (
            first_group.primary_asset_id in first_group.asset_ids
        )
    else:
        assert first_group.primary_asset_id in first_group.asset_ids, (
            f"非 needs_review 组的 primary_asset_id ({first_group.primary_asset_id!r}) "
            f"必须落在 asset_ids ({first_group.asset_ids!r}) 中"
        )

    # ---------- 断言：default_candidates ----------
    assert cut_after.default_candidates, "default_candidates 不应为空"
    pool_ids = {dc.asset_id for dc in cut_after.default_candidates if dc.asset_id}
    assets_by_id = {a.asset_id: a for a in cut_after.assets if a.asset_id}
    for group in cut_after.similar_groups:
        if group.primary_asset_id is None:
            continue
        primary_id = group.primary_asset_id
        in_pool = primary_id in pool_ids
        primary_asset = assets_by_id.get(primary_id)
        primary_default_selected = (
            primary_asset is not None
            and primary_asset.edit_candidate_status
            == EditCandidateStatus.default_selected
        )
        assert in_pool or primary_default_selected, (
            f"primary_asset_id={primary_id!r} 既不在 default_candidates，"
            "edit_candidate_status 也不是 default_selected"
        )

    # ---------- 断言：clustering 头部 ----------
    assert cut_after.clustering is not None
    assert cut_after.clustering.status in {"completed", "partial"}, (
        f"clustering.status 应为 completed/partial，实际 {cut_after.clustering.status!r}"
    )
    assert cut_after.clustering.groups_count >= 1
    assert cut_after.clustering.started_at
    assert cut_after.clustering.finished_at

    # ---------- 断言：ClusterResult 摘要 ----------
    assert result.total_groups == cut_after.clustering.groups_count
    assert result.cut_index_path == str(cut_path)
    assert result.log_path

    # ---------- 断言：日志文件 ----------
    log_files = _list_cluster_logs(min_mtime=test_start_mtime)
    assert log_files, (
        f"本次 cluster 应在 {logs_dir(_DEMO_SLUG, _DEMO_BASE_DIR)} 下生成 cluster-*.jsonl"
    )
    log_path = Path(result.log_path)
    assert log_path.is_file()
    assert log_path in log_files

    log_text = log_path.read_text(encoding="utf-8")
    lines = log_text.strip().splitlines()
    assert lines, "cluster JSONL 至少 1 行"
    first_event = json.loads(lines[0])
    last_event = json.loads(lines[-1])
    assert first_event["event"] == "stage_start"
    assert last_event["event"] == "stage_end"

    # ---------- 断言：日志脱敏（spec Q24） ----------
    api_key = os.environ[_API_KEY_ENV]
    assert api_key not in log_text
    assert ("Bearer " + api_key) not in log_text


# ---------------------------------------------------------------------------
# SubTask 9.3：cluster 重跑清空旧状态
# ---------------------------------------------------------------------------


def test_cluster_rerun_clears_old_state():
    """SubTask 9.3：在已有 clustering.status='completed' 的基础上再跑一次 cluster。

    本用例自包含：先跑一次 cluster 拿到 baseline，再跑一次 cluster 验证新旧不互相覆盖。
    断言：
    - 旧的 similar_groups / default_candidates 被清空后重新生成；
    - 新 clustering.started_at 严格晚于旧值；
    - 新生成新的 logs/cluster-*.jsonl 文件，与旧文件路径不同。
    """
    _require_api_key()
    _require_demo_scan_completed()

    cut_path = cut_index_path(_DEMO_SLUG, _DEMO_BASE_DIR)

    # ---------- Run 1：建立 baseline ----------
    _reset_cluster_state()
    first_start_mtime = time.time() - 1.0
    first_result = cluster_runner.cluster(_DEMO_SLUG, base_dir=_DEMO_BASE_DIR)
    cut_after_first = read_cut_index(cut_path)
    assert cut_after_first.clustering is not None
    first_started_at = cut_after_first.clustering.started_at
    assert first_started_at
    first_log_path = Path(first_result.log_path)
    assert first_log_path.is_file()
    assert first_log_path.stat().st_mtime >= first_start_mtime

    # 至少留 1s 间隔，让 cluster_log_path 的秒级时间戳能滚到下一秒（避免文件名冲突）。
    time.sleep(1.1)

    # ---------- Run 2：在 clustering=completed 的基础上重跑 ----------
    second_start_mtime = time.time() - 1.0
    second_result = cluster_runner.cluster(_DEMO_SLUG, base_dir=_DEMO_BASE_DIR)
    cut_after_second = read_cut_index(cut_path)

    # 重跑应保留有效结果（不空）且产生新 started_at。
    assert cut_after_second.clustering is not None
    assert cut_after_second.clustering.status in {"completed", "partial"}
    second_started_at = cut_after_second.clustering.started_at
    assert second_started_at
    assert second_started_at > first_started_at, (
        f"重跑后的 started_at ({second_started_at}) 应严格晚于第一次 ({first_started_at})"
    )

    # 重跑后 similar_groups / default_candidates 应被重新构建（spec ADDED Requirements）。
    # 这里"被清空后重新生成"对外可观测的体现是：仍然非空（因为 demo-scan 有连号样本天然形成组）。
    assert cut_after_second.similar_groups, "重跑后 similar_groups 应被重建"
    assert cut_after_second.default_candidates, "重跑后 default_candidates 应被重建"

    # 新日志文件路径与旧不同（cluster_log_path 用秒级时间戳，sleep 已保证滚到下一秒）。
    second_log_path = Path(second_result.log_path)
    assert second_log_path.is_file()
    assert second_log_path != first_log_path, (
        f"重跑应生成新日志文件，但路径与第一次相同：{second_log_path}"
    )
    assert second_log_path.stat().st_mtime >= second_start_mtime

    # 旧日志没有被覆盖（仍存在）。
    assert first_log_path.is_file(), "旧日志文件应被保留，不应被覆盖"
