"""只允许经 Validator 和 Store 改变选片任务状态的 Tool。"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from .asset_tools import AssetBrowser
from .models import (
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
    ) -> None:
        self.browser = browser
        self.state = state
        self.store = store
        self.validator = validator

    def as_langchain_tools(self) -> list[StructuredTool]:
        def asset_list(page: int = 1) -> dict[str, Any]:
            """分页列出素材摘要。完成前必须从第 1 页浏览到最后一页。"""
            return self.browser.list_page(page)

        def asset_get(asset_id: str) -> dict[str, Any]:
            """打开一个素材的完整索引详情和已有片段建议。"""
            return self.browser.get(asset_id)

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
            }

        def selection_candidate_add(
            asset_id: str,
            start_sec: float,
            end_sec: float,
            category_ids: list[str],
            reason: str,
            recommended_use: str | None = None,
        ) -> dict[str, Any]:
            """新增一个主选候选；候选 ID 由代码生成。"""
            parameters = {
                "asset_id": asset_id,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "category_ids": category_ids,
                "reason": reason,
                "recommended_use": recommended_use,
            }
            candidate = SelectionCandidate(
                candidate_id=f"candidate-{len(self.state.candidates) + 1:03d}",
                asset_id=asset_id,
                start_sec=start_sec,
                end_sec=end_sec,
                category_ids=category_ids,
                recommended_use=recommended_use,
                reason=reason,
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
            self.store.save(self.state)
            self.store.append_event(
                "candidate_added",
                tool="selection_candidate_add",
                data={"candidate": candidate.model_dump(mode="json")},
            )
            return {"accepted": True, "candidate": candidate.model_dump(mode="json")}

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
                data={"candidate_count": len(self.state.candidates)},
            )
            return {"accepted": True, "status": self.state.status}

        return [
            StructuredTool.from_function(asset_list, name="asset_list"),
            StructuredTool.from_function(asset_get, name="asset_get"),
            StructuredTool.from_function(
                selection_categories_save,
                name="selection_categories_save",
            ),
            StructuredTool.from_function(
                selection_candidate_add,
                name="selection_candidate_add",
            ),
            StructuredTool.from_function(
                selection_finish_request,
                name="selection_finish_request",
            ),
        ]


__all__ = ["SelectionTools"]
