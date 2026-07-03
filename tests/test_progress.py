"""实时进度 reporter 的纯单测。"""

from __future__ import annotations

from tripclipper.progress import PeriodicProgressReporter


def test_reporter_emits_start_first_third_and_final_lines():
    lines: list[str] = []
    reporter = PeriodicProgressReporter("sample", emit=lines.append)

    reporter.start(total=6, skipped=2, extra="并发=3")
    reporter.advance_success()
    reporter.advance_success()
    reporter.advance_failure()
    reporter.advance_success()
    reporter.advance_success()
    reporter.advance_failure()

    assert lines == [
        "[sample] 开始：总计 6，跳过 2，并发=3",
        "[sample] 1/6（成功 1 / 失败 0 / 跳过 2）",
        "[sample] 3/6（成功 2 / 失败 1 / 跳过 2）",
        "[sample] 6/6（成功 4 / 失败 2 / 跳过 2）",
    ]


def test_reporter_handles_zero_total_without_crashing():
    lines: list[str] = []
    reporter = PeriodicProgressReporter("scan", emit=lines.append)

    reporter.start(total=0, extra="非媒体 3")

    assert lines == ["[scan] 开始：总计 0，非媒体 3"]
