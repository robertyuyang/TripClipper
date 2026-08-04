"""只允许经 Validator 和 Store 改变选片任务状态的 Tool。"""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.tools import StructuredTool

from .asset_tools import AssetBrowser
from .frames import FrameSampler
from .models import (
    AssetInspection,
    CategoryDraft,
    SelectionCandidate,
    SelectionCategory,
    SelectionState,
)
from .store import SelectionStore
from .validator import SelectionValidationError, SelectionValidator


class SelectionTools:
    def __init__(
        self,
        browser: AssetBrowser,
        state: SelectionState,
        store: SelectionStore,
        validator: SelectionValidator,
        *,
        frame_sampler: FrameSampler | None = None,
    ) -> None:
        self.browser = browser
        self.state = state
        self.store = store
        self.validator = validator
        self.frame_sampler = frame_sampler
        self._next_candidate_number = max(
            (
                int(item.candidate_id.rsplit("-", 1)[-1])
                for item in state.candidates
                if item.candidate_id.rsplit("-", 1)[-1].isdigit()
            ),
            default=0,
        ) + 1

    def as_langchain_tools(self) -> list[StructuredTool]:
        def inspection_progress() -> dict[str, Any]:
            inspections = self.state.asset_progress.inspections
            inspected_ids = {inspection.asset_id for inspection in inspections}
            required_count = self.validator.required_inspection_count(self.state)
            category_minimum = min(8, self.validator.total_assets)
            category_progress: dict[str, dict[str, int]] = {}
            for category in self.state.categories:
                count = len(
                    {
                        inspection.asset_id
                        for inspection in inspections
                        if category.category_id in inspection.category_ids
                    }
                )
                required = category_minimum if category.required else 0
                category_progress[category.category_id] = {
                    "inspection_count": count,
                    "required_inspection_count": required,
                    "remaining_inspection_count": max(0, required - count),
                }
            return {
                "required_inspection_count": required_count,
                "inspection_count": len(inspected_ids),
                "remaining_inspection_count": max(
                    0, required_count - len(inspected_ids)
                ),
                "category_progress": category_progress,
            }

        def save_inspections(
            inspections: list[AssetInspection],
            *,
            tool_name: str,
        ) -> dict[str, Any]:
            parameters = {
                "inspections": [
                    inspection.model_dump(mode="json") for inspection in inspections
                ]
            }
            try:
                self.validator.validate_inspection_batch(inspections, self.state)
            except SelectionValidationError as exc:
                self.store.append_event(
                    "change_validated",
                    tool=tool_name,
                    data={
                        "accepted": False,
                        "blockers": exc.blockers,
                        "parameters": parameters,
                    },
                )
                return {"accepted": False, "blockers": exc.blockers}

            details = self.browser.get_many(
                [inspection.asset_id for inspection in inspections]
            )
            merged = {
                inspection.asset_id: inspection
                for inspection in self.state.asset_progress.inspections
            }
            for inspection in inspections:
                previous = merged.get(inspection.asset_id)
                if previous is not None:
                    inspection = inspection.model_copy(
                        update={
                            "category_ids": sorted(
                                set(previous.category_ids)
                                | set(inspection.category_ids)
                            )
                        }
                    )
                merged[inspection.asset_id] = inspection

            opened_asset_ids = list(self.state.asset_progress.opened_asset_ids)
            for inspection in inspections:
                if inspection.asset_id not in opened_asset_ids:
                    opened_asset_ids.append(inspection.asset_id)
            self.state.asset_progress.inspections = list(merged.values())
            self.state.asset_progress.opened_asset_ids = opened_asset_ids
            self.store.append_event(
                "change_validated",
                tool=tool_name,
                data={"accepted": True, "blockers": [], "parameters": parameters},
            )
            self.store.save(self.state)
            for inspection in inspections:
                saved_inspection = merged[inspection.asset_id]
                self.store.append_event(
                    "asset_opened",
                    tool=tool_name,
                    data={
                        "asset_id": inspection.asset_id,
                        "category_ids": saved_inspection.category_ids,
                        "shortlist_reason": saved_inspection.shortlist_reason,
                    },
                )
            if tool_name == "asset_get_batch":
                self.store.append_event(
                    "asset_batch_opened",
                    tool=tool_name,
                    data={
                        "asset_ids": [item.asset_id for item in inspections],
                        "count": len(inspections),
                    },
                )
            return {
                "accepted": True,
                "assets": details,
                **inspection_progress(),
            }

        def asset_list(page: int = 1) -> dict[str, Any]:
            """分页列出素材摘要。完成前必须从第 1 页浏览到最后一页。"""
            return self.browser.list_page(page)

        def asset_get(
            asset_id: str,
            category_ids: list[str],
            shortlist_reason: str,
        ) -> dict[str, Any]:
            """打开一个素材的完整索引详情，并记录其分类比较用途。"""
            return save_inspections(
                [
                    AssetInspection(
                        asset_id=asset_id,
                        category_ids=category_ids,
                        shortlist_reason=shortlist_reason,
                    )
                ],
                tool_name="asset_get",
            )

        def asset_get_batch(
            inspections: list[AssetInspection],
        ) -> dict[str, Any]:
            """批量打开 1～10 个不同素材的完整索引详情。"""
            return save_inspections(inspections, tool_name="asset_get_batch")

        def asset_frames_sample(
            asset_id: str,
            start_sec: float,
            end_sec: float,
            count: int,
        ) -> list[dict[str, Any]]:
            """查看指定素材和时间范围的采样帧，优先复用已有视觉证据。"""
            if self.frame_sampler is None:
                raise RuntimeError("当前任务没有配置采样帧目录")
            result = self.frame_sampler.sample(asset_id, start_sec, end_sec, count)
            return self.frame_sampler.tool_content(result)

        def selection_categories_save(
            categories: list[CategoryDraft],
        ) -> dict[str, Any]:
            """保存完整分类列表；分类 ID 由代码生成并在结果中返回。"""
            parameters = {
                "categories": [
                    category.model_dump(mode="json") for category in categories
                ]
            }
            try:
                self.validator.validate_categories(categories, self.state.categories)
            except SelectionValidationError as exc:
                self.store.append_event(
                    "change_validated",
                    tool="selection_categories_save",
                    data={
                        "accepted": False,
                        "blockers": exc.blockers,
                        "parameters": parameters,
                    },
                )
                return {"accepted": False, "blockers": exc.blockers}
            self.store.append_event(
                "change_validated",
                tool="selection_categories_save",
                data={
                    "accepted": True,
                    "blockers": [],
                    "parameters": parameters,
                },
            )
            if self.state.categories:
                self.state.categories = [
                    SelectionCategory.model_validate(category.model_dump())
                    for category in categories
                ]
            else:
                self.state.categories = [
                    SelectionCategory(
                        category_id=f"category-{index:03d}",
                        **category.model_dump(exclude={"category_id"}),
                    )
                    for index, category in enumerate(categories, start=1)
                ]
            self.store.save(self.state)
            self.store.append_event(
                "categories_saved",
                tool="selection_categories_save",
                data={
                    "categories": [
                        category.model_dump(mode="json")
                        for category in self.state.categories
                    ]
                },
            )
            return {
                "accepted": True,
                "categories": [
                    category.model_dump(mode="json")
                    for category in self.state.categories
                ],
                **inspection_progress(),
            }

        def selection_candidate_add(
            asset_id: str,
            start_sec: float,
            end_sec: float,
            category_ids: list[str],
            reason: str,
            status: Literal["primary", "alternate", "needs_review"] = "primary",
            recommended_use: str | None = None,
            alternative_to_ids: list[str] | None = None,
            review_reason: str | None = None,
        ) -> dict[str, Any]:
            """新增主选、备选或待人工复核候选；候选 ID 由代码生成。"""
            parameters = {
                "asset_id": asset_id,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "category_ids": category_ids,
                "reason": reason,
                "status": status,
                "recommended_use": recommended_use,
                "alternative_to_ids": alternative_to_ids or [],
                "review_reason": review_reason,
            }
            candidate = SelectionCandidate(
                candidate_id=f"candidate-{self._next_candidate_number:03d}",
                asset_id=asset_id,
                start_sec=start_sec,
                end_sec=end_sec,
                status=status,
                category_ids=category_ids,
                recommended_use=recommended_use,
                reason=reason,
                alternative_to_ids=alternative_to_ids or [],
                review_reason=review_reason,
            )
            try:
                self.validator.validate_candidate_add(candidate, self.state)
            except SelectionValidationError as exc:
                self.store.append_event(
                    "change_validated",
                    tool="selection_candidate_add",
                    data={
                        "accepted": False,
                        "blockers": exc.blockers,
                        "parameters": parameters,
                    },
                )
                return {"accepted": False, "blockers": exc.blockers}
            self.store.append_event(
                "change_validated",
                tool="selection_candidate_add",
                data={
                    "accepted": True,
                    "blockers": [],
                    "parameters": parameters,
                },
            )
            self.state.candidates.append(candidate)
            self._next_candidate_number += 1
            self.store.save(self.state)
            self.store.append_event(
                "candidate_added",
                tool="selection_candidate_add",
                data={"candidate": candidate.model_dump(mode="json")},
            )
            return {"accepted": True, "candidate": candidate.model_dump(mode="json")}

        def selection_candidate_update(
            candidate_id: str,
            start_sec: float,
            end_sec: float,
            status: Literal["primary", "alternate", "needs_review"],
            category_ids: list[str],
            reason: str,
            recommended_use: str | None = None,
            alternative_to_ids: list[str] | None = None,
            review_reason: str | None = None,
        ) -> dict[str, Any]:
            """用完整的新内容修订一个既有候选。"""
            existing = next(
                (
                    candidate
                    for candidate in self.state.candidates
                    if candidate.candidate_id == candidate_id
                ),
                None,
            )
            if existing is None:
                blockers = [f"候选不存在：{candidate_id}"]
                self.store.append_event(
                    "change_validated",
                    tool="selection_candidate_update",
                    data={
                        "accepted": False,
                        "blockers": blockers,
                        "parameters": {"candidate_id": candidate_id},
                    },
                )
                return {"accepted": False, "blockers": blockers}
            parameters = {
                "candidate_id": candidate_id,
                "asset_id": existing.asset_id,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "status": status,
                "category_ids": category_ids,
                "reason": reason,
                "recommended_use": recommended_use,
                "alternative_to_ids": alternative_to_ids or [],
                "review_reason": review_reason,
            }
            candidate = SelectionCandidate(**parameters)
            try:
                self.validator.validate_candidate_update(candidate, self.state)
            except SelectionValidationError as exc:
                self.store.append_event(
                    "change_validated",
                    tool="selection_candidate_update",
                    data={
                        "accepted": False,
                        "blockers": exc.blockers,
                        "parameters": parameters,
                    },
                )
                return {"accepted": False, "blockers": exc.blockers}
            self.state.candidates = [
                candidate if item.candidate_id == candidate_id else item
                for item in self.state.candidates
            ]
            self.store.save(self.state)
            self.store.append_event(
                "change_validated",
                tool="selection_candidate_update",
                data={"accepted": True, "blockers": [], "parameters": parameters},
            )
            self.store.append_event(
                "candidate_updated",
                tool="selection_candidate_update",
                data={"candidate": candidate.model_dump(mode="json")},
            )
            return {"accepted": True, "candidate": candidate.model_dump(mode="json")}

        def selection_candidate_remove(
            candidate_id: str,
            reason: str,
        ) -> dict[str, Any]:
            """移除候选并把原因写入事件；仍被引用的候选不可移除。"""
            blockers: list[str] = []
            if candidate_id not in {
                candidate.candidate_id for candidate in self.state.candidates
            }:
                blockers.append(f"候选不存在：{candidate_id}")
            references = sorted(
                candidate.candidate_id
                for candidate in self.state.candidates
                if candidate_id in candidate.alternative_to_ids
            )
            if references:
                blockers.append(
                    f"候选 {candidate_id} 仍被其他候选引用："
                    + ", ".join(references)
                )
            if not reason.strip():
                blockers.append("移除原因不能为空")
            parameters = {"candidate_id": candidate_id, "reason": reason}
            self.store.append_event(
                "change_validated",
                tool="selection_candidate_remove",
                data={
                    "accepted": not blockers,
                    "blockers": blockers,
                    "parameters": parameters,
                },
            )
            if blockers:
                return {"accepted": False, "blockers": blockers}
            self.state.candidates = [
                candidate
                for candidate in self.state.candidates
                if candidate.candidate_id != candidate_id
            ]
            self.store.save(self.state)
            self.store.append_event(
                "candidate_removed",
                tool="selection_candidate_remove",
                data=parameters,
            )
            return {"accepted": True, "candidate_id": candidate_id}

        def selection_finish_request() -> dict[str, Any]:
            """请求完成选片；确定性校验通过后状态立即变成 completed。"""
            try:
                self.validator.validate_completion(self.state)
            except SelectionValidationError as exc:
                self.store.append_event(
                    "completion_validated",
                    tool="selection_finish_request",
                    data={
                        "accepted": False,
                        "blockers": exc.blockers,
                        "parameters": {},
                    },
                )
                return {"accepted": False, "blockers": exc.blockers}
            self.store.append_event(
                "completion_validated",
                tool="selection_finish_request",
                data={"accepted": True, "blockers": [], "parameters": {}},
            )
            self.state.status = "completed"
            self.store.save(self.state)
            self.store.append_event(
                "selection_completed",
                tool="selection_finish_request",
                data={
                    "candidate_count": len(self.state.candidates),
                    "inspection_count": len(
                        {
                            item.asset_id
                            for item in self.state.asset_progress.inspections
                        }
                    ),
                    "required_inspection_count": (
                        self.validator.required_inspection_count(self.state)
                    ),
                    "primary_union_duration_sec": (
                        self.validator.primary_union_duration(self.state.candidates)
                    ),
                },
            )
            return {"accepted": True, "status": self.state.status}

        tools = [
            StructuredTool.from_function(asset_list, name="asset_list"),
            StructuredTool.from_function(asset_get, name="asset_get"),
            StructuredTool.from_function(asset_get_batch, name="asset_get_batch"),
            StructuredTool.from_function(
                selection_categories_save,
                name="selection_categories_save",
            ),
            StructuredTool.from_function(
                selection_candidate_add,
                name="selection_candidate_add",
            ),
            StructuredTool.from_function(
                selection_candidate_update,
                name="selection_candidate_update",
            ),
            StructuredTool.from_function(
                selection_candidate_remove,
                name="selection_candidate_remove",
            ),
            StructuredTool.from_function(
                selection_finish_request,
                name="selection_finish_request",
            ),
        ]
        if self.frame_sampler is not None:
            tools.insert(
                3,
                StructuredTool.from_function(
                    asset_frames_sample,
                    name="asset_frames_sample",
                ),
            )
        return tools


__all__ = ["SelectionTools"]
