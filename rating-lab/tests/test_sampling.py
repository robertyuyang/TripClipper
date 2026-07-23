"""评分实验室抽样测试。"""

from __future__ import annotations

from collections import Counter

from tripclipper.models import Asset, AssetType, SubjectType

from helpers import make_assets


def test_default_rating_quotas_total_thirty() -> None:
    from rating_lab.sampling import DEFAULT_RATING_QUOTAS

    assert DEFAULT_RATING_QUOTAS == {1: 1, 2: 3, 3: 9, 4: 15, 5: 2}
    assert sum(DEFAULT_RATING_QUOTAS.values()) == 30


def test_select_fixed_sample_honors_quotas_and_seed() -> None:
    from rating_lab.sampling import select_fixed_sample

    assets = make_assets()
    quotas = {1: 1, 2: 3, 3: 5, 4: 7, 5: 2}

    first = select_fixed_sample(assets, quotas=quotas, seed=42)
    second = select_fixed_sample(list(reversed(assets)), quotas=quotas, seed=42)

    assert Counter(asset.rating for asset in first) == Counter(quotas)
    assert [asset.asset_id for asset in first] == [asset.asset_id for asset in second]


def test_select_fixed_sample_spreads_across_sessions_first() -> None:
    from rating_lab.sampling import select_fixed_sample

    assets = [
        Asset(
            asset_id=f"session-{session}-item-{index}",
            rating=4,
            session_id=f"session_{session:02d}",
            type=AssetType.video,
            subject_type=SubjectType.activity,
        )
        for session in range(5)
        for index in range(6)
    ]

    selected = select_fixed_sample(assets, quotas={4: 5}, seed=0)

    assert {asset.session_id for asset in selected} == {
        "session_00",
        "session_01",
        "session_02",
        "session_03",
        "session_04",
    }


def test_select_fixed_sample_prioritizes_sessions_over_subject_buckets() -> None:
    from rating_lab.sampling import select_fixed_sample

    subjects = [SubjectType.activity, SubjectType.people, SubjectType.landscape]
    assets = [
        Asset(
            asset_id=f"s{session}-{index}",
            rating=4,
            session_id=f"s{session}",
            type=AssetType.video,
            subject_type=subject,
        )
        for session in range(3)
        for index, subject in enumerate(subjects)
    ]

    selected = select_fixed_sample(assets, quotas={4: 3}, seed=1)

    assert {asset.session_id for asset in selected} == {"s0", "s1", "s2"}
    assert {asset.subject_type for asset in selected} == set(subjects)


def test_select_fixed_sample_fills_short_quota_from_remaining_assets() -> None:
    from rating_lab.sampling import select_fixed_sample

    assets = [
        Asset(asset_id=f"r4-{index}", rating=4, session_id=f"s{index}")
        for index in range(8)
    ] + [Asset(asset_id="r5-only", rating=5, session_id="s5")]

    selected = select_fixed_sample(assets, quotas={1: 1, 4: 3, 5: 2}, seed=7)

    assert len(selected) == 6
    assert len({asset.asset_id for asset in selected}) == 6
    assert Counter(asset.rating for asset in selected)[5] == 1


def test_build_manifest_freezes_selected_asset_metadata() -> None:
    from rating_lab.sampling import build_manifest

    assets = make_assets()
    manifest = build_manifest(
        project_slug="demo",
        assets=assets,
        quotas={1: 1, 2: 1, 3: 1, 4: 2, 5: 1},
        seed=42,
    )

    assert manifest["schema_version"] == 1
    assert manifest["project_slug"] == "demo"
    assert manifest["seed"] == 42
    assert manifest["rating_quotas"] == {"1": 1, "2": 1, "3": 1, "4": 2, "5": 1}
    assert manifest["actual_rating_counts"] == {
        "1": 1,
        "2": 1,
        "3": 1,
        "4": 2,
        "5": 1,
    }
    assert len(manifest["assets"]) == 6
    assert manifest["assets"][0].keys() == {
        "asset_id",
        "relative_path",
        "baseline_rating",
        "type",
        "session_id",
        "subject_type",
        "shot_scale",
    }
