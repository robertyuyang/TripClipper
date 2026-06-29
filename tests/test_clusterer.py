"""M4 Task 8 单元测试：``clusterer.py`` 纯函数与候选池后处理（SubTask 8.1-8.10）。

测试纪律（spec Q1/Q2/Q17）：

- **零 mock / 零 monkeypatch 替换业务函数**。本文件只针对 ``clusterer.py`` 的纯
  函数 + 候选池后处理逻辑做断言。
- 不构造伪造的"分析结果"写回 ``cut_index.json``（这里根本不写盘）。
- 不依赖外网 / 不依赖真实 ``.env``。
"""

from __future__ import annotations

from typing import Optional

from tripclipper.clusterer import (
    _UnionFind,
    _similarity_signals,
    _tags_jaccard,
    _text_jaccard_2gram,
    apply_similarity_states,
    build_default_candidates,
    cluster_candidates,
)
from tripclipper.models import (
    AnalysisStatus,
    Asset,
    CutIndex,
    EditCandidateStatus,
    ProjectInfo,
    ShotScale,
    SimilarGroup,
    SimilarSelection,
    SubjectType,
)


# ---------------------------------------------------------------------------
# Helper：合成 Asset
# ---------------------------------------------------------------------------


def _make_asset(
    asset_id: str,
    *,
    modified_time: Optional[str] = None,
    subject_type: Optional[SubjectType] = None,
    shot_scale: Optional[ShotScale] = None,
    primary_subject: Optional[str] = None,
    tags: Optional[list[str]] = None,
    rating: Optional[int] = None,
    analysis_status: AnalysisStatus = AnalysisStatus.analyzed,
    relative_path: Optional[str] = None,
    similar_selection: Optional[SimilarSelection] = None,
) -> Asset:
    return Asset(
        asset_id=asset_id,
        relative_path=relative_path or asset_id,
        analysis_status=analysis_status,
        modified_time=modified_time,
        subject_type=subject_type,
        shot_scale=shot_scale,
        primary_subject=primary_subject,
        tags=tags or [],
        rating=rating,
        metadata={},
        similar_selection=similar_selection,
    )


def _make_cut(assets: list[Asset]) -> CutIndex:
    project = ProjectInfo(project_name="t", project_slug="t")
    return CutIndex(project=project, assets=assets)


# ---------------------------------------------------------------------------
# SubTask 8.1：_text_jaccard_2gram
# ---------------------------------------------------------------------------


def test_text_jaccard_identical():
    assert _text_jaccard_2gram("海边夕阳人物", "海边夕阳人物") == 1.0


def test_text_jaccard_reordered_positive():
    # 语序变化会显著降低 2-gram Jaccard 但仍有交集（"海边" 在两边都有）。
    score = _text_jaccard_2gram("海边夕阳人物", "海边人物夕阳")
    assert score > 0.0


def test_text_jaccard_disjoint_zero():
    assert _text_jaccard_2gram("海边", "山顶") == 0.0


def test_text_jaccard_empty_zero():
    assert _text_jaccard_2gram("", "") == 0.0


def test_text_jaccard_single_char_zero():
    # 单字：长度 < 2，按规则返回 0.0。
    assert _text_jaccard_2gram("海", "海") == 0.0


# ---------------------------------------------------------------------------
# SubTask 8.2：_tags_jaccard
# ---------------------------------------------------------------------------


def test_tags_jaccard_identical():
    assert _tags_jaccard(["海", "夕阳"], ["海", "夕阳"]) == 1.0


def test_tags_jaccard_partial_overlap():
    # {海,夕阳} ∩ {海,人物} = {海}；并集 = 3。
    assert _tags_jaccard(["海", "夕阳"], ["海", "人物"]) == 1 / 3


def test_tags_jaccard_both_empty_zero():
    assert _tags_jaccard([], []) == 0.0


def test_tags_jaccard_one_empty_zero():
    assert _tags_jaccard(["海"], []) == 0.0


# ---------------------------------------------------------------------------
# SubTask 8.3：_similarity_signals 强信号轨
# ---------------------------------------------------------------------------


def test_similarity_strong_track_within_60s_same_subject_hit():
    a = _make_asset(
        "a", modified_time="2025-06-12T11:41:46+00:00", subject_type=SubjectType.building
    )
    b = _make_asset(
        "b", modified_time="2025-06-12T11:42:16+00:00", subject_type=SubjectType.building
    )
    similar, track = _similarity_signals(a, b)
    assert similar is True
    assert track == "强信号轨"


def test_similarity_strong_track_outside_60s_no_hit():
    a = _make_asset(
        "a", modified_time="2025-06-12T11:41:46+00:00", subject_type=SubjectType.building
    )
    b = _make_asset(
        "b", modified_time="2025-06-12T11:43:16+00:00", subject_type=SubjectType.building
    )
    similar, _ = _similarity_signals(a, b)
    assert similar is False


def test_similarity_strong_track_subject_mismatch_no_hit():
    a = _make_asset(
        "a", modified_time="2025-06-12T11:41:46+00:00", subject_type=SubjectType.building
    )
    b = _make_asset(
        "b", modified_time="2025-06-12T11:42:00+00:00", subject_type=SubjectType.people
    )
    similar, _ = _similarity_signals(a, b)
    assert similar is False


def test_similarity_strong_track_missing_modified_time_no_hit():
    a = _make_asset("a", subject_type=SubjectType.building)
    b = _make_asset("b", subject_type=SubjectType.building)
    # 双方 modified_time 缺失 → 强信号轨不命中。语义轨也无 shot_scale → 不命中。
    similar, _ = _similarity_signals(a, b)
    assert similar is False


def test_similarity_strong_track_reads_top_level_modified_time_not_metadata():
    # 回归测试：modified_time 是 Asset 顶层字段，clusterer 必须从 asset.modified_time
    # 读取，不能从 asset.metadata['modified_time'] 读。否则强信号轨永远命不中真实
    # scan 数据，连号素材会被遗漏。
    a = Asset(
        asset_id="a",
        relative_path="a",
        analysis_status=AnalysisStatus.analyzed,
        modified_time="2025-06-12T11:41:46+00:00",
        subject_type=SubjectType.building,
        shot_scale=ShotScale.medium,
        metadata={},
    )
    b = Asset(
        asset_id="b",
        relative_path="b",
        analysis_status=AnalysisStatus.analyzed,
        modified_time="2025-06-12T11:42:16+00:00",
        subject_type=SubjectType.building,
        shot_scale=ShotScale.wide,  # 景别不同：语义轨命不中
        metadata={},
    )
    similar, track = _similarity_signals(a, b)
    assert similar is True
    assert track == "强信号轨"


# ---------------------------------------------------------------------------
# SubTask 8.4：_similarity_signals 语义信号轨
# ---------------------------------------------------------------------------


def test_similarity_semantic_track_subject_text_hit():
    a = _make_asset(
        "a",
        subject_type=SubjectType.landscape,
        shot_scale=ShotScale.wide,
        primary_subject="海边夕阳",
    )
    b = _make_asset(
        "b",
        subject_type=SubjectType.landscape,
        shot_scale=ShotScale.wide,
        primary_subject="海边夕阳",
    )
    similar, track = _similarity_signals(a, b)
    assert similar is True
    assert track == "语义信号轨"


def test_similarity_semantic_track_tags_hit():
    a = _make_asset(
        "a",
        subject_type=SubjectType.landscape,
        shot_scale=ShotScale.wide,
        primary_subject="完全不同的描述",
        tags=["海", "夕阳", "黄昏"],
    )
    b = _make_asset(
        "b",
        subject_type=SubjectType.landscape,
        shot_scale=ShotScale.wide,
        primary_subject="另一段毫不相关的话",
        tags=["海", "夕阳", "黄昏"],
    )
    # tags Jaccard = 3/3 = 1.0 ≥ 0.5 → 命中。
    similar, track = _similarity_signals(a, b)
    assert similar is True
    assert track == "语义信号轨"


def test_similarity_semantic_track_below_thresholds_no_hit():
    a = _make_asset(
        "a",
        subject_type=SubjectType.landscape,
        shot_scale=ShotScale.wide,
        primary_subject="海边",
        tags=["海"],
    )
    b = _make_asset(
        "b",
        subject_type=SubjectType.landscape,
        shot_scale=ShotScale.wide,
        primary_subject="山顶",
        tags=["山"],
    )
    similar, _ = _similarity_signals(a, b)
    assert similar is False


# ---------------------------------------------------------------------------
# SubTask 8.5：_UnionFind 并查集传递闭包
# ---------------------------------------------------------------------------


def test_union_find_transitive_closure():
    uf = _UnionFind()
    for x in ("A", "B", "C", "D"):
        uf.add(x)
    uf.union("A", "B")
    uf.union("B", "C")

    groups = uf.groups()
    # 找到 A 所在组。
    a_root = uf.find("A")
    assert sorted(groups[a_root]) == ["A", "B", "C"]
    # D 独立。
    d_root = uf.find("D")
    assert groups[d_root] == ["D"]


# ---------------------------------------------------------------------------
# SubTask 8.6：cluster_candidates 过滤未 analyzed
# ---------------------------------------------------------------------------


def test_cluster_candidates_filters_non_analyzed():
    # 7 条 analyzed，其中 4 条同 subject_type=building 同时间窗口构成强信号轨组。
    base = "2025-06-12T11:41:46+00:00"
    times = [
        "2025-06-12T11:41:46+00:00",
        "2025-06-12T11:41:56+00:00",
        "2025-06-12T11:42:06+00:00",
        "2025-06-12T11:42:16+00:00",
    ]
    analyzed_assets = [
        _make_asset(
            f"an_{i}",
            modified_time=t,
            subject_type=SubjectType.building,
            analysis_status=AnalysisStatus.analyzed,
        )
        for i, t in enumerate(times)
    ]
    # 另外 3 条 analyzed 但孤立（不同 subject_type 或时间远离）。
    analyzed_assets.append(
        _make_asset(
            "an_4",
            modified_time="2025-06-12T13:00:00+00:00",
            subject_type=SubjectType.people,
            analysis_status=AnalysisStatus.analyzed,
        )
    )
    analyzed_assets.append(
        _make_asset(
            "an_5",
            modified_time="2025-06-12T14:00:00+00:00",
            subject_type=SubjectType.food,
            analysis_status=AnalysisStatus.analyzed,
        )
    )
    analyzed_assets.append(
        _make_asset(
            "an_6",
            modified_time="2025-06-12T15:00:00+00:00",
            subject_type=SubjectType.activity,
            analysis_status=AnalysisStatus.analyzed,
        )
    )
    # 3 条 scanned —— 应被 cluster_candidates 过滤掉，绝不进任何组。
    scanned_assets = [
        _make_asset(
            f"sc_{i}",
            modified_time=base,
            subject_type=SubjectType.building,
            analysis_status=AnalysisStatus.scanned,
        )
        for i in range(3)
    ]
    all_assets = analyzed_assets + scanned_assets

    groups = cluster_candidates(all_assets)
    assert len(groups) >= 1

    analyzed_ids = {a.asset_id for a in analyzed_assets}
    for group in groups:
        for member_id in group.asset_ids:
            assert member_id in analyzed_ids, (
                f"组成员 {member_id} 不属于 analyzed 集合"
            )


# ---------------------------------------------------------------------------
# SubTask 8.7：build_default_candidates 主体×景别平衡触发
# ---------------------------------------------------------------------------


def test_build_default_candidates_balance_trims_dominant_bucket():
    assets: list[Asset] = []
    # 18 条 (building, wide)，rating 1-5 散布。
    for i in range(18):
        assets.append(
            _make_asset(
                f"bw_{i}",
                subject_type=SubjectType.building,
                shot_scale=ShotScale.wide,
                rating=(i % 5) + 1,
                similar_selection=SimilarSelection.none,
            )
        )
    # 12 条其他 (subject_type, shot_scale) 组合。
    other_combos = [
        (SubjectType.people, ShotScale.medium),
        (SubjectType.food, ShotScale.close_up),
        (SubjectType.landscape, ShotScale.full),
        (SubjectType.activity, ShotScale.wide),
    ]
    for i in range(12):
        st, ss = other_combos[i % len(other_combos)]
        assets.append(
            _make_asset(
                f"ot_{i}",
                subject_type=st,
                shot_scale=ss,
                rating=(i % 5) + 1,
                similar_selection=SimilarSelection.none,
            )
        )

    cut = _make_cut(assets)
    candidates = build_default_candidates(cut)

    # default_selected 计数。
    default_selected = [
        a
        for a in cut.assets
        if a.edit_candidate_status == EditCandidateStatus.default_selected
    ]
    bw_in_default = [
        a
        for a in default_selected
        if a.subject_type == SubjectType.building
        and a.shot_scale == ShotScale.wide
    ]
    # 占比 ≤ 50%。
    if default_selected:
        share = len(bw_in_default) / len(default_selected)
        assert share <= 0.5 + 1e-9

    # 被降为 alternate 的 ≤ floor(30 * 0.2) = 6。
    demoted = [
        a
        for a in cut.assets
        if a.edit_candidate_status == EditCandidateStatus.alternate
    ]
    assert len(demoted) <= 6

    # 候选池非空，且仅含 default_selected。
    assert candidates
    assert len(candidates) == len(default_selected)


# ---------------------------------------------------------------------------
# SubTask 8.8：build_default_candidates 不触发分支（< 20）
# ---------------------------------------------------------------------------


def test_build_default_candidates_below_trigger_no_trim():
    # 15 条平均分布的 Asset，全 analyzed + similar_selection=none。
    combos = [
        (SubjectType.people, ShotScale.medium),
        (SubjectType.landscape, ShotScale.wide),
        (SubjectType.food, ShotScale.close_up),
    ]
    assets: list[Asset] = []
    for i in range(15):
        st, ss = combos[i % len(combos)]
        assets.append(
            _make_asset(
                f"a_{i}",
                subject_type=st,
                shot_scale=ss,
                rating=(i % 5) + 1,
                similar_selection=SimilarSelection.none,
            )
        )

    cut = _make_cut(assets)
    candidates = build_default_candidates(cut)

    assert len(candidates) == 15
    # 全部 default_selected，无 alternate 降级。
    for a in cut.assets:
        assert a.edit_candidate_status == EditCandidateStatus.default_selected
        assert a.edit_candidate_priority is not None


# ---------------------------------------------------------------------------
# SubTask 8.9：build_default_candidates 修剪上限分支
# ---------------------------------------------------------------------------


def test_build_default_candidates_trim_cap_protects_extreme_distribution():
    # 25 条 (building, wide) + 5 条其他。
    assets: list[Asset] = []
    for i in range(25):
        assets.append(
            _make_asset(
                f"bw_{i}",
                subject_type=SubjectType.building,
                shot_scale=ShotScale.wide,
                rating=(i % 5) + 1,
                similar_selection=SimilarSelection.none,
            )
        )
    for i in range(5):
        assets.append(
            _make_asset(
                f"ot_{i}",
                subject_type=SubjectType.people,
                shot_scale=ShotScale.medium,
                rating=(i % 5) + 1,
                similar_selection=SimilarSelection.none,
            )
        )

    cut = _make_cut(assets)
    build_default_candidates(cut)

    demoted = [
        a
        for a in cut.assets
        if a.edit_candidate_status == EditCandidateStatus.alternate
    ]
    # 修剪上限 floor(30 * 0.2) = 6。
    assert len(demoted) <= 6

    default_selected = [
        a
        for a in cut.assets
        if a.edit_candidate_status == EditCandidateStatus.default_selected
    ]
    bw_in_default = [
        a
        for a in default_selected
        if a.subject_type == SubjectType.building
        and a.shot_scale == ShotScale.wide
    ]
    # 极端集中场景下，达到修剪上限后 building+wide 仍占多数（修剪未能让其降到 50%）。
    assert len(bw_in_default) > len(default_selected) - len(bw_in_default)


# ---------------------------------------------------------------------------
# SubTask 8.10：build_default_candidates needs_review 不进池
# ---------------------------------------------------------------------------


def test_build_default_candidates_needs_review_excluded():
    assets: list[Asset] = []
    # 5 条 analyzed + similar_selection=none → 默认入选。
    for i in range(5):
        assets.append(
            _make_asset(
                f"ok_{i}",
                subject_type=SubjectType.people,
                shot_scale=ShotScale.medium,
                rating=4,
                similar_selection=SimilarSelection.none,
                analysis_status=AnalysisStatus.analyzed,
            )
        )
    # 3 条 analysis_failed → needs_review。
    for i in range(3):
        assets.append(
            _make_asset(
                f"fail_{i}",
                subject_type=SubjectType.people,
                rating=3,
                analysis_status=AnalysisStatus.analysis_failed,
            )
        )
    # 2 条 analyzed 但 similar_selection=needs_review → needs_review。
    for i in range(2):
        assets.append(
            _make_asset(
                f"nr_{i}",
                subject_type=SubjectType.people,
                rating=3,
                analysis_status=AnalysisStatus.analyzed,
                similar_selection=SimilarSelection.needs_review,
            )
        )

    cut = _make_cut(assets)
    candidates = build_default_candidates(cut)

    # 5 条 ok_* 全部 default_selected 进 default_candidates。
    assert len(candidates) == 5
    candidate_ids = {c.asset_id for c in candidates}
    for i in range(5):
        assert f"ok_{i}" in candidate_ids

    # 后 5 条全部 needs_review，且不在 default_candidates 列表。
    by_id = {a.asset_id: a for a in cut.assets}
    for i in range(3):
        assert (
            by_id[f"fail_{i}"].edit_candidate_status
            == EditCandidateStatus.needs_review
        )
        assert f"fail_{i}" not in candidate_ids
    for i in range(2):
        assert (
            by_id[f"nr_{i}"].edit_candidate_status
            == EditCandidateStatus.needs_review
        )
        assert f"nr_{i}" not in candidate_ids


# ---------------------------------------------------------------------------
# Bonus: apply_similarity_states 基本回写正确（贴在 8.5/8.6 边界，强化覆盖）
# ---------------------------------------------------------------------------


def test_apply_similarity_states_writes_back_basic():
    a1 = _make_asset("a1", rating=5)
    a2 = _make_asset("a2", rating=4)
    a3 = _make_asset("a3", rating=3)
    cut = _make_cut([a1, a2, a3])

    group = SimilarGroup(
        similar_group_id="group_1",
        asset_ids=["a1", "a2", "a3"],
        primary_asset_id="a1",
        alternate_asset_ids=["a2"],
        rejected_asset_ids=["a3"],
        confidence=0.9,
        basis=["相近构图"],
        needs_review=False,
    )
    apply_similarity_states(cut, [group])

    by_id = {a.asset_id: a for a in cut.assets}
    assert by_id["a1"].similar_selection == SimilarSelection.primary
    assert by_id["a1"].similar_rank == 1
    assert by_id["a2"].similar_selection == SimilarSelection.alternate
    assert by_id["a3"].similar_selection == SimilarSelection.rejected
