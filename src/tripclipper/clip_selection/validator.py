"""选片状态的确定性校验；不承担审美判断。"""

from __future__ import annotations

from collections import defaultdict
import math

from .models import (
    CategoryDraft,
    SelectionCandidate,
    SelectionCategory,
    SelectionState,
)


class SelectionValidationError(ValueError):
    def __init__(self, blockers: list[str]) -> None:
        self.blockers = blockers
        super().__init__("；".join(blockers))


class SelectionValidator:
    def __init__(
        self,
        asset_durations: dict[str, float],
        *,
        asset_ids: set[str] | None = None,
        total_pages: int,
    ) -> None:
        self.asset_durations = asset_durations
        self.asset_ids = set(asset_ids or asset_durations)
        self.total_assets = len(self.asset_ids)
        self.total_pages = total_pages

    def required_inspection_count(self, state: SelectionState) -> int:
        required_categories = sum(category.required for category in state.categories)
        desired = max(
            30,
            math.ceil(self.total_assets * 0.2),
            required_categories * 8,
        )
        return min(self.total_assets, desired)

    def validate_categories(
        self,
        categories: list[CategoryDraft],
        existing_categories: list[SelectionCategory] | None = None,
    ) -> None:
        blockers: list[str] = []
        if not categories:
            blockers.append("至少需要一个内容分类")
        names: set[str] = set()
        existing_ids = {
            category.category_id for category in (existing_categories or [])
        }
        submitted_ids: set[str] = set()
        for category in categories:
            name = category.name.strip()
            if not name:
                blockers.append("分类名称不能为空")
            elif name in names:
                blockers.append(f"分类名称重复：{name}")
            names.add(name)
            if not category.purpose.strip():
                blockers.append(f"分类 {name or '<未命名>'} 缺少用途说明")
            if existing_ids:
                if category.category_id not in existing_ids:
                    blockers.append(
                        f"重复保存分类时必须使用已有分类 ID：{category.category_id or '<缺失>'}"
                    )
                elif category.category_id in submitted_ids:
                    blockers.append(f"分类 ID 重复：{category.category_id}")
                else:
                    submitted_ids.add(category.category_id)
            elif category.category_id is not None:
                blockers.append("首次保存分类时不得自行提供分类 ID")
        missing_ids = sorted(existing_ids - submitted_ids)
        if missing_ids:
            blockers.append(
                "重复保存分类时必须提交完整分类列表，缺少："
                + ", ".join(missing_ids)
            )
        if blockers:
            raise SelectionValidationError(blockers)

    def validate_candidate(
        self,
        candidate: SelectionCandidate,
        state: SelectionState,
    ) -> None:
        blockers: list[str] = []
        duration = self.asset_durations.get(candidate.asset_id)
        if duration is None:
            blockers.append(f"素材不存在：{candidate.asset_id}")
        elif not (0 <= candidate.start_sec < candidate.end_sec <= duration):
            blockers.append(
                f"时间范围必须满足 0 <= start_sec < end_sec <= {duration:g}"
            )
        category_ids = {category.category_id for category in state.categories}
        missing = sorted(set(candidate.category_ids) - category_ids)
        if missing:
            blockers.append(f"分类引用不存在：{', '.join(missing)}")
        if not candidate.reason.strip():
            blockers.append("候选理由不能为空")
        if blockers:
            raise SelectionValidationError(blockers)

    def validate_candidate_add(
        self,
        candidate: SelectionCandidate,
        state: SelectionState,
    ) -> None:
        """校验新增候选，并阻止不可修订的最小候选池越过容量上限。"""
        self.validate_candidate(candidate, state)
        projected_duration = self._primary_union_duration(
            [*state.candidates, candidate]
        )
        maximum = state.target_duration_sec * 1.5
        if projected_duration > maximum:
            raise SelectionValidationError(
                [
                    f"加入后主选总时长为 {projected_duration:g} 秒，"
                    f"超过主选容量上限 {maximum:g} 秒"
                ]
            )

    def validate_completion(self, state: SelectionState) -> None:
        blockers: list[str] = []
        if not state.categories:
            blockers.append("尚未建立内容分类")
        expected_pages = set(range(1, self.total_pages + 1))
        missing_pages = sorted(expected_pages - set(state.asset_progress.listed_pages))
        if missing_pages:
            blockers.append(
                "尚未浏览全部素材分页：" + ", ".join(map(str, missing_pages))
            )

        primary_categories = {
            category_id
            for candidate in state.candidates
            for category_id in candidate.category_ids
        }
        for category in state.categories:
            if (
                category.required
                and category.category_id not in primary_categories
                and not (category.missing_reason or "").strip()
            ):
                blockers.append(f"必要分类缺少主选：{category.name}")

        for candidate in state.candidates:
            try:
                self.validate_candidate(candidate, state)
            except SelectionValidationError as exc:
                blockers.extend(
                    f"{candidate.candidate_id}: {blocker}"
                    for blocker in exc.blockers
                )

        primary_duration = self._primary_union_duration(state.candidates)
        minimum = state.target_duration_sec
        maximum = minimum * 1.5
        if not minimum <= primary_duration <= maximum:
            blockers.append(
                f"主选总时长 {primary_duration:g} 秒不在 {minimum:g}～{maximum:g} 秒范围内"
            )
        if state.unresolved:
            blockers.append("仍存在未解决的高优先级问题")
        if blockers:
            raise SelectionValidationError(blockers)

    @staticmethod
    def _primary_union_duration(candidates: list[SelectionCandidate]) -> float:
        by_asset: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for candidate in candidates:
            by_asset[candidate.asset_id].append(
                (candidate.start_sec, candidate.end_sec)
            )

        total = 0.0
        for intervals in by_asset.values():
            start, end = sorted(intervals)[0]
            for next_start, next_end in sorted(intervals)[1:]:
                if next_start <= end:
                    end = max(end, next_end)
                else:
                    total += end - start
                    start, end = next_start, next_end
            total += end - start
        return total


__all__ = ["SelectionValidationError", "SelectionValidator"]
