"""评分实验室模块边界测试。"""

from __future__ import annotations


def test_domain_functions_are_exposed_by_focused_modules() -> None:
    from rating_lab.evaluation import compare_ratings
    from rating_lab.review import (
        write_manifest,
        write_manual_labels,
        write_manual_review_html,
    )
    from rating_lab.runner import reserve_run_dir, run_calibration, write_results
    from rating_lab.sampling import (
        DEFAULT_RATING_QUOTAS,
        build_manifest,
        project_fingerprint,
        select_fixed_sample,
    )

    assert DEFAULT_RATING_QUOTAS == {1: 1, 2: 3, 3: 9, 4: 15, 5: 2}
    assert all(
        callable(function)
        for function in (
            compare_ratings,
            write_manifest,
            write_manual_labels,
            write_manual_review_html,
            reserve_run_dir,
            run_calibration,
            write_results,
            build_manifest,
            project_fingerprint,
            select_fixed_sample,
        )
    )
