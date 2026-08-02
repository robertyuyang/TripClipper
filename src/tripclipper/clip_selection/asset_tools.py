"""只读浏览 ``cut_index.json`` 的选片 Tool。"""

from __future__ import annotations

import math
from typing import Any

from tripclipper.models import Asset

from .models import SelectionState
from .store import SelectionStore


class AssetBrowser:
    def __init__(
        self,
        assets: list[Asset],
        state: SelectionState,
        store: SelectionStore,
        *,
        page_size: int = 20,
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size 必须大于 0")
        self.assets = assets
        self.state = state
        self.store = store
        self.page_size = page_size
        self.by_id = {
            asset.asset_id: asset for asset in assets if asset.asset_id is not None
        }

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(len(self.assets) / self.page_size))

    @property
    def asset_durations(self) -> dict[str, float]:
        durations: dict[str, float] = {}
        for asset_id, asset in self.by_id.items():
            value = asset.metadata.get("duration")
            if isinstance(value, (int, float)) and value >= 0:
                durations[asset_id] = float(value)
        return durations

    def list_page(self, page: int = 1) -> dict[str, Any]:
        if not 1 <= page <= self.total_pages:
            raise ValueError(f"page 必须位于 1～{self.total_pages}")
        start = (page - 1) * self.page_size
        selected = self.assets[start : start + self.page_size]
        if page not in self.state.asset_progress.listed_pages:
            self.state.asset_progress.listed_pages.append(page)
            self.state.asset_progress.listed_pages.sort()
            self.store.save(self.state)
        self.store.append_event(
            "asset_listed",
            tool="asset_list",
            data={"page": page, "returned": len(selected)},
        )
        return {
            "page": page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
            "total_assets": len(self.assets),
            "assets": [self._summary(asset) for asset in selected],
        }

    def get(self, asset_id: str) -> dict[str, Any]:
        asset = self.by_id.get(asset_id)
        if asset is None:
            raise ValueError(f"素材不存在：{asset_id}")
        if asset_id not in self.state.asset_progress.opened_asset_ids:
            self.state.asset_progress.opened_asset_ids.append(asset_id)
            self.store.save(self.state)
        self.store.append_event(
            "asset_opened",
            tool="asset_get",
            data={"asset_id": asset_id},
        )
        return asset.model_dump(mode="json", by_alias=True)

    @staticmethod
    def _summary(asset: Asset) -> dict[str, Any]:
        return {
            "asset_id": asset.asset_id,
            "filename": asset.filename,
            "duration_sec": asset.metadata.get("duration"),
            "summary": asset.summary,
            "rating": asset.rating,
            "subject_type": (
                asset.subject_type.value if asset.subject_type is not None else None
            ),
            "shot_scale": (
                asset.shot_scale.value if asset.shot_scale is not None else None
            ),
            "suggestion_count": len(asset.clip_suggestions),
            "suggestion_overview": [
                suggestion.model_dump(
                    mode="json",
                    by_alias=True,
                    include={"in_", "out", "role", "rating"},
                )
                for suggestion in asset.clip_suggestions
            ],
        }


__all__ = ["AssetBrowser"]
