"""评分实验室测试辅助数据。"""

from __future__ import annotations

from tripclipper.models import Asset, AssetType, SubjectType


def make_assets() -> list[Asset]:
    assets: list[Asset] = []
    counts = {1: 2, 2: 8, 3: 20, 4: 30, 5: 5}
    for rating, count in counts.items():
        for index in range(count):
            assets.append(
                Asset(
                    asset_id=f"r{rating}-{index:02d}",
                    relative_path=f"day-{index % 4}/r{rating}-{index:02d}.mp4",
                    type=AssetType.video if index % 5 else AssetType.image,
                    rating=rating,
                    session_id=f"session_{index % 5:02d}",
                    subject_type=(
                        SubjectType.activity
                        if index % 2
                        else SubjectType.people_landscape
                    ),
                )
            )
    return assets
