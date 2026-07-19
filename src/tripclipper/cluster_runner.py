"""M4 Stage 3 cluster 流程编排（仿 :mod:`tripclipper.analyzer`，串行版本）。

读 ``cut_index.json`` → 硬卡 ``analysis`` 已完成 → 重跑时清空旧分组 →
:func:`clusterer.cluster_candidates` 出候选组 → 逐组 :class:`Arbiter`（最多
top12 参与仲裁，超额按 rating desc 标 alternate）→
:func:`clusterer.apply_similarity_states` 写回 → :func:`clusterer.build_default_candidates`
出候选池 → 阶段头尾 + 每组完成增量落盘。

不在此模块：抽帧（M2）、单素材分析（M3 :mod:`tripclipper.analyzer`）、导出（M5）。
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from .arbiter import Arbiter, ArbiterError, ArbitrationResult
from .clusterer import (
    GROUP_ARBITRATION_LIMIT,
    apply_similarity_states,
    build_default_candidates,
    cluster_candidates,
)
from .config import EditingIntent, ModelConfig, load_config, load_software_config
from .cut_index import read_cut_index, write_cut_index
from .logs import ClusterLogger
from .models import (
    AnalysisStatus,
    Asset,
    ClusteringInfo,
    CutIndex,
    EditCandidateStatus,
    Failure,
    SimilarGroup,
)
from .paths import cut_index_path

_PathLike = Union[str, Path]

_CLUSTER_STAGE = "cluster"

# 中文 reason 模板（spec Q5/Q6/Q16/Q18）。
_REASON_OVERFLOW = "组内素材过多，仅 rating Top 12 参与组级仲裁"
_REASON_ARBITRATION_FAILED = "仲裁失败，待人工确认"
_REASON_LOW_CONFIDENCE = "组内置信度不足，待人工确认"


# ---------------------------------------------------------------------------
# 公共结果与异常
# ---------------------------------------------------------------------------


@dataclass
class ClusterResult:
    """一次 cluster 的运行摘要，供 CLI / runner / API 直接展示。"""

    total_groups: int = 0
    primary_decided: int = 0
    needs_review_groups: int = 0
    arbitration_failures: int = 0
    pool_size: int = 0
    alternate_count: int = 0
    needs_review_count: int = 0
    excluded_count: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    log_path: Optional[str] = None
    cut_index_path: Optional[str] = None


class ClusterRunnerError(Exception):
    """编排无法启动时抛出的面向用户的清晰错误。"""


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _rating_desc_key(asset: Asset) -> tuple:
    """按 rating desc 排序的 key（``rating is None`` 视为 -1）。次序稳定加 asset_id。"""
    rating = asset.rating if asset.rating is not None else -1
    return (-rating, asset.asset_id or "")


def _clear_previous_run(cut: CutIndex) -> None:
    """重跑时清空所有 cluster 相关字段（spec ADDED Requirements: cluster 重跑自动清空旧分组）。"""
    cut.similar_groups = []
    cut.default_candidates = []
    cut.failures = [f for f in cut.failures if f.stage != _CLUSTER_STAGE]
    for asset in cut.assets:
        asset.similar_group_id = None
        asset.similar_selection = None
        asset.similar_rank = None
        asset.similar_reason = None
        asset.edit_candidate_status = None
        asset.edit_candidate_priority = None
        asset.edit_candidate_reason = None
    cut.clustering = None


def _summarize_errors(arbitration_failures: int, needs_review_groups: int) -> Optional[str]:
    """生成 ``error_summary`` 中文短文案。无任何失败/置信度不足返回 ``None``。"""
    parts: list[str] = []
    if arbitration_failures > 0:
        parts.append(f"{arbitration_failures} 组仲裁失败")
    if needs_review_groups > 0:
        parts.append(f"{needs_review_groups} 组置信度不足")
    return "、".join(parts) if parts else None


def _resolve_similar_reason(
    asset: Asset,
    group_state: dict,
    overflow_ids_by_group: dict,
) -> Optional[str]:
    """根据组状态与 overflow 标记，决定单条 asset 的 ``similar_reason``。"""
    gid = asset.similar_group_id
    if not gid or not asset.asset_id:
        return None
    if asset.asset_id in overflow_ids_by_group.get(gid, set()):
        return _REASON_OVERFLOW
    state = group_state.get(gid)
    if state is None:
        return None
    kind = state.get("kind")
    if kind == "failure":
        return _REASON_ARBITRATION_FAILED
    result: Optional[ArbitrationResult] = state.get("result")
    if result is not None:
        per_asset = result.reason_by_asset.get(asset.asset_id)
        if per_asset:
            return per_asset
    if kind == "low_confidence":
        return _REASON_LOW_CONFIDENCE
    return None


# ---------------------------------------------------------------------------
# 公共编排入口
# ---------------------------------------------------------------------------


def cluster(slug: str, *, base_dir: Optional[_PathLike] = None) -> ClusterResult:
    """M4 cluster 流程主入口（spec Q5/Q8/Q12/Q13/Q16/Q18/Q19）。"""

    index_path = cut_index_path(slug, base_dir)

    # ---------- 硬卡 1：cut_index.json 必须存在 ----------
    if not index_path.exists():
        raise ClusterRunnerError(
            f"项目尚未初始化或扫描（未找到 {index_path}）。请先运行 "
            f"'tripclipper init' 与 'tripclipper analyze --stage scan'。"
        )

    cut: CutIndex = read_cut_index(index_path)

    # ---------- 硬卡 2：analysis 必须 completed/partial ----------
    analysis = cut.analysis
    if analysis is None or analysis.status not in {"completed", "partial"}:
        current_status = analysis.status if analysis is not None else None
        raise ClusterRunnerError(
            f"项目尚未完成分析（analysis.status={current_status}）。"
            "请先运行 'tripclipper analyze <slug> --stage full'。"
        )

    # ---------- 软警告：仅 sample 阶段 ----------
    if analysis.stage == "sample":
        analyzed_count = sum(
            1 for a in cut.assets if a.analysis_status == AnalysisStatus.analyzed
        )
        sys.stderr.write(
            f"警告：仅基于 sample 阶段的 {analyzed_count} 个素材聚组；"
            "建议先跑 full 再 cluster\n"
        )

    # ---------- 加载软件级配置 + 项目 editing_intent ----------
    config_path = cut.project.config_path
    if not config_path:
        raise ClusterRunnerError(
            "cut_index.json 缺少 project.config_path，无法定位 project.yaml；"
            "请重新运行 init。"
        )
    project_config = load_config(config_path)
    software_config = load_software_config(legacy_project_path=config_path)
    llm_config: ModelConfig = software_config.llm
    editing_intent: EditingIntent = project_config.editing_intent

    # ---------- 重跑清空 ----------
    if cut.clustering is not None:
        _clear_previous_run(cut)
        write_cut_index(index_path, cut)

    # ---------- 构造 logger ----------
    logger = ClusterLogger(slug, Path(base_dir) if base_dir is not None else None)

    # ---------- 项目级 Arbiter 探测 ----------
    try:
        arbiter = Arbiter(llm_config, editing_intent)
    except ArbiterError as exc:
        cut.failures.append(
            Failure(
                stage=_CLUSTER_STAGE,
                target=slug,
                reason=str(exc),
                suggestion=(
                    "请检查 .env 中 TRIPCLIPPER_MODEL_API_KEY 是否设置，"
                    "并确认软件配置中的 model_config.provider / base_url / "
                    "vision_model 完整"
                ),
                blocking=True,
                occurred_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        write_cut_index(index_path, cut)
        raise ClusterRunnerError(f"Arbiter 初始化失败：{exc}") from exc

    # ---------- 阶段头落盘 ----------
    started_at = datetime.now(timezone.utc).isoformat()
    cut.clustering = ClusteringInfo(
        provider=llm_config.provider,
        vision_model=llm_config.vision_model,
        text_model=llm_config.text_model,
        stage=_CLUSTER_STAGE,
        started_at=started_at,
        finished_at=None,
        status="running",
        error_summary=None,
        groups_count=0,
        arbitration_failures=0,
    )
    write_cut_index(index_path, cut)

    logger.stage_start(stage=_CLUSTER_STAGE, total=len(cut.assets), concurrency=1)
    run_start = time.monotonic()

    # ---------- 本地启发式聚组 ----------
    eligible = [
        a for a in cut.assets if a.analysis_status == AnalysisStatus.analyzed
    ]
    logger.cluster_start(stage=_CLUSTER_STAGE, total_assets=len(eligible))
    candidate_groups = cluster_candidates(cut.assets)
    logger.cluster_done(
        groups_count=len(candidate_groups), eligible_assets=len(eligible)
    )

    assets_by_id: dict[str, Asset] = {
        a.asset_id: a for a in cut.assets if a.asset_id
    }

    # ---------- 逐组仲裁 ----------
    primary_decided = 0
    needs_review_groups = 0
    arbitration_failures = 0
    group_state: dict[str, dict] = {}
    overflow_ids_by_group: dict[str, set[str]] = {}

    for idx, candidate in enumerate(candidate_groups, start=1):
        group_id = f"group_{idx}"

        # 还原 Asset 实例 + 按 rating desc 排序。
        group_assets_sorted = [
            assets_by_id[aid]
            for aid in candidate.asset_ids
            if aid in assets_by_id
        ]
        group_assets_sorted.sort(key=_rating_desc_key)

        # Top12 截断（spec Q5）。
        if len(group_assets_sorted) > GROUP_ARBITRATION_LIMIT:
            top_assets = group_assets_sorted[:GROUP_ARBITRATION_LIMIT]
            overflow_assets = group_assets_sorted[GROUP_ARBITRATION_LIMIT:]
        else:
            top_assets = group_assets_sorted
            overflow_assets = []

        overflow_ids = {a.asset_id for a in overflow_assets if a.asset_id}
        overflow_ids_by_group[group_id] = overflow_ids
        member_ids = [a.asset_id for a in group_assets_sorted if a.asset_id]

        logger.arbitration_start(group_id=group_id, asset_count=len(top_assets))

        t0 = time.monotonic()
        try:
            result = arbiter.arbitrate(top_assets)
        except ArbiterError as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            reason = str(exc)
            logger.arbitration_failed(
                group_id=group_id,
                error=reason,
                retry_attempt=1,
            )
            arbitration_failures += 1
            needs_review_groups += 1

            sim_group = SimilarGroup(
                similar_group_id=group_id,
                asset_ids=member_ids,
                primary_asset_id=None,
                alternate_asset_ids=[],
                rejected_asset_ids=[],
                confidence=None,
                basis=[],
                needs_review=True,
                reason=_REASON_ARBITRATION_FAILED,
            )
            cut.similar_groups.append(sim_group)
            group_state[group_id] = {"kind": "failure", "result": None}

            if exc.transient:
                suggestion = "瞬时错误请重跑 cluster；非瞬时请检查 prompt / 换 vision_model"
            else:
                suggestion = "非瞬时错误：检查 prompt / 换 vision_model / 检查 API key"
            cut.failures.append(
                Failure(
                    stage=_CLUSTER_STAGE,
                    target=group_id,
                    reason=reason,
                    suggestion=suggestion,
                    blocking=False,
                    occurred_at=datetime.now(timezone.utc).isoformat(),
                )
            )

            # 增量落盘（spec Q8）。
            write_cut_index(index_path, cut)
            continue

        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.arbitration_done(
            group_id=group_id,
            confidence=result.confidence,
            primary_asset_id=result.primary_asset_id,
            http_code=200,
            latency_ms=latency_ms,
        )

        # 仲裁成功（含低置信度走 needs_review 分支）。
        if result.needs_review:
            needs_review_groups += 1
            group_kind = "low_confidence"
            primary_for_group: Optional[str] = None
            group_reason: Optional[str] = _REASON_LOW_CONFIDENCE
        else:
            primary_decided += 1
            group_kind = "success"
            primary_for_group = result.primary_asset_id
            group_reason = None

        # overflow 追加到 alternate 尾部（保持 Arbiter 返回的顺序在前）。
        alternate_with_overflow = list(result.alternate_asset_ids) + [
            a.asset_id for a in overflow_assets if a.asset_id
        ]

        sim_group = SimilarGroup(
            similar_group_id=group_id,
            asset_ids=member_ids,
            primary_asset_id=primary_for_group,
            alternate_asset_ids=alternate_with_overflow,
            rejected_asset_ids=list(result.rejected_asset_ids),
            confidence=result.confidence,
            basis=list(result.basis),
            needs_review=result.needs_review,
            reason=group_reason,
        )
        cut.similar_groups.append(sim_group)
        group_state[group_id] = {"kind": group_kind, "result": result}

        # 增量落盘（spec Q8）。
        write_cut_index(index_path, cut)

    # ---------- 应用相似度状态 ----------
    apply_similarity_states(cut, cut.similar_groups)

    # ---------- 写 similar_reason ----------
    for asset in cut.assets:
        if not asset.asset_id:
            continue
        if asset.similar_group_id is None:
            # apply_similarity_states 已重置非组员的 similar_reason=None。
            continue
        asset.similar_reason = _resolve_similar_reason(
            asset, group_state, overflow_ids_by_group
        )

    # ---------- 候选池 ----------
    logger.candidates_start()
    build_default_candidates(cut)
    pool_size = len(cut.default_candidates)
    alternate_count = sum(
        1
        for a in cut.assets
        if a.edit_candidate_status == EditCandidateStatus.alternate
    )
    needs_review_count = sum(
        1
        for a in cut.assets
        if a.edit_candidate_status == EditCandidateStatus.needs_review
    )
    excluded_count = sum(
        1
        for a in cut.assets
        if a.edit_candidate_status == EditCandidateStatus.excluded
    )
    logger.candidates_done(
        pool_size=pool_size,
        alternate_count=alternate_count,
        needs_review_count=needs_review_count,
        excluded_count=excluded_count,
    )

    # ---------- 阶段尾落盘 ----------
    finished_at = datetime.now(timezone.utc).isoformat()
    total_groups = len(candidate_groups)
    if total_groups == 0:
        status = "completed"
    elif arbitration_failures == 0:
        status = "completed"
    elif arbitration_failures < total_groups:
        status = "partial"
    else:
        status = "failed"

    cut.clustering.finished_at = finished_at
    cut.clustering.status = status
    cut.clustering.groups_count = total_groups
    cut.clustering.arbitration_failures = arbitration_failures
    cut.clustering.error_summary = _summarize_errors(
        arbitration_failures, needs_review_groups
    )
    write_cut_index(index_path, cut)

    duration_ms = int((time.monotonic() - run_start) * 1000)
    logger.stage_end(
        stage=_CLUSTER_STAGE,
        succeeded=primary_decided,
        failed=arbitration_failures,
        skipped=0,
        duration_ms=duration_ms,
    )
    logger.close()

    return ClusterResult(
        total_groups=total_groups,
        primary_decided=primary_decided,
        needs_review_groups=needs_review_groups,
        arbitration_failures=arbitration_failures,
        pool_size=pool_size,
        alternate_count=alternate_count,
        needs_review_count=needs_review_count,
        excluded_count=excluded_count,
        started_at=started_at,
        finished_at=finished_at,
        log_path=str(logger.log_path),
        cut_index_path=str(index_path),
    )


__all__ = ["ClusterResult", "ClusterRunnerError", "cluster"]
