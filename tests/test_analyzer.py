"""M3 Analyzer 与 JSONL 日志的纯函数单元测试（Task 7：SubTask 7.3/7.4/7.5/7.8）。

测试纪律（spec Q1/Q2/Q17）：

- **零 mock / 零 monkeypatch 替换业务函数**。``_persist_callback`` 是
  :func:`tripclipper.analyzer._run` 自身暴露的测试钩子（公共 API 不暴露），
  注入计数 callback 不算 mock 业务函数，是 spec 显式预留的注入点。
- 本文件**不**调 ``Provider.analyze``，**不**构造伪造分析结果写回
  ``cut_index.json``。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from tripclipper.analyzer import (
    _classify_reason,
    _should_process,
    _stratified_sample,
    _summarize_errors,
    _top_directory,
)
from tripclipper.logs import AnalyzeLogger
from tripclipper.models import AnalysisStatus, Asset, AssetType


# ---------------------------------------------------------------------------
# SubTask 7.3：_stratified_sample 分层、比例、可复现
# ---------------------------------------------------------------------------


def _make_assets() -> list[Asset]:
    """合成 100 个素材：10 video / 80 image / 10 audio，跨 5 个顶层目录均匀分布。"""
    items: list[Asset] = []
    top_dirs = ["d1", "d2", "d3", "d4", "d5"]
    for idx in range(10):
        items.append(
            Asset(
                asset_id=f"v-{idx}",
                type=AssetType.video,
                filename=f"video_{idx}.mp4",
                relative_path=f"{top_dirs[idx % 5]}/video_{idx}.mp4",
            )
        )
    for idx in range(80):
        items.append(
            Asset(
                asset_id=f"i-{idx}",
                type=AssetType.image,
                filename=f"image_{idx}.jpg",
                relative_path=f"{top_dirs[idx % 5]}/image_{idx}.jpg",
            )
        )
    for idx in range(10):
        items.append(
            Asset(
                asset_id=f"a-{idx}",
                type=AssetType.audio,
                filename=f"audio_{idx}.mp3",
                relative_path=f"{top_dirs[idx % 5]}/audio_{idx}.mp3",
            )
        )
    return items


def test_top_directory_handles_edge_cases():
    assert _top_directory("a/b/c.mp4") == "a"
    assert _top_directory("a.mp4") == "_root"
    assert _top_directory("") == "_root"
    assert _top_directory(None) == "_root"
    assert _top_directory("/leading/slash.mp4") == "_root"
    # Windows 风格路径分隔符也归一化。
    assert _top_directory("d1\\nested\\file.mp4") == "d1"


def test_stratified_sample_zero_and_empty():
    assets = _make_assets()
    assert _stratified_sample(assets, 0) == []
    assert _stratified_sample([], 25) == []
    assert _stratified_sample(assets, -3) == []


def test_stratified_sample_oversize_returns_all_sorted():
    assets = _make_assets()
    out = _stratified_sample(assets, 999)
    # 全量返回（按 relative_path 排序，长度一致）。
    assert len(out) == len(assets)
    rps = [a.relative_path for a in out]
    assert rps == sorted(rps)


def test_stratified_sample_picks_25_across_types_and_dirs():
    assets = _make_assets()
    selected = _stratified_sample(assets, 25)
    assert len(selected) == 25
    types = Counter(a.type.value for a in selected)
    # 两级 largest-remainder 分配的 deterministic 行为：
    # 第一层 type 配额：
    #   video : 25 * 10/100 = 2.5  → floor 2；fractional 0.5
    #   image : 25 * 80/100 = 20.0 → floor 20；fractional 0
    #   audio : 25 * 10/100 = 2.5  → floor 2；fractional 0.5
    #   余额 1 个按 (-fractional, key) 排序补齐 —— audio 字典序排在 video
    #   之前 → 余额给 audio。最终 video=2 / image=20 / audio=3。
    # 三类都被抽到，符合 spec Q6 期望。
    assert types["video"] == 2
    assert types["image"] == 20
    assert types["audio"] == 3
    # image 覆盖全部 5 个顶层目录（每桶 4 个）。
    image_dirs = {
        _top_directory(a.relative_path)
        for a in selected
        if a.type.value == "image"
    }
    assert image_dirs == {"d1", "d2", "d3", "d4", "d5"}


def test_stratified_sample_larger_size_covers_all_three_types():
    # sample_size=40 时 video/audio 各拿到 5 个余额名额，三类都被抽到。
    assets = _make_assets()
    selected = _stratified_sample(assets, 40)
    assert len(selected) == 40
    types = Counter(a.type.value for a in selected)
    assert set(types.keys()) == {"video", "image", "audio"}
    assert types["image"] >= types["video"]
    assert types["image"] >= types["audio"]


def test_stratified_sample_is_reproducible_with_same_seed():
    assets = _make_assets()
    first = _stratified_sample(assets, 25, seed=42)
    second = _stratified_sample(assets, 25, seed=42)
    assert [a.asset_id for a in first] == [a.asset_id for a in second]


def test_stratified_sample_different_seed_yields_different_pick():
    assets = _make_assets()
    s1 = _stratified_sample(assets, 25, seed=42)
    s2 = _stratified_sample(assets, 25, seed=7)
    # 不同 seed 下大概率不同（理论上小概率全同，但在 100→25 的规模下不会）。
    assert [a.asset_id for a in s1] != [a.asset_id for a in s2]


# ---------------------------------------------------------------------------
# SubTask 7.4：_should_process 跳过判定（纯函数版，不调 Provider.analyze）
# ---------------------------------------------------------------------------


def test_should_process_force_processes_all():
    for status in AnalysisStatus:
        asset = Asset(asset_id="x", type=AssetType.video, analysis_status=status)
        assert _should_process(asset, force=True) is True


def test_should_process_no_force_skips_only_analyzed():
    cases = {
        AnalysisStatus.scanned: True,
        AnalysisStatus.analyzing: True,
        AnalysisStatus.analysis_failed: True,
        AnalysisStatus.analyzed: False,  # 唯一跳过
    }
    for status, expected in cases.items():
        asset = Asset(asset_id="x", type=AssetType.video, analysis_status=status)
        assert _should_process(asset, force=False) is expected, status


def test_should_process_counts_match_spec_example():
    # 5 个 analyzed + 3 个 scanned，force=False 跳 5、force=True 处理 8。
    assets = (
        [
            Asset(
                asset_id=f"done-{i}",
                type=AssetType.image,
                analysis_status=AnalysisStatus.analyzed,
            )
            for i in range(5)
        ]
        + [
            Asset(
                asset_id=f"new-{i}",
                type=AssetType.image,
                analysis_status=AnalysisStatus.scanned,
            )
            for i in range(3)
        ]
    )
    selected_no_force = [a for a in assets if _should_process(a, force=False)]
    selected_force = [a for a in assets if _should_process(a, force=True)]
    assert len(selected_no_force) == 3
    assert len(selected_force) == 8


# ---------------------------------------------------------------------------
# SubTask 7.5：增量落盘 5+5+2 边界（通过 _persist_callback 注入计数 callback）
# ---------------------------------------------------------------------------


def test_persist_callback_fires_at_5_10_and_final():
    """模拟 12 个素材完成回调序列，验证 _persist 的触发节奏。

    实际编排里：
    - 阶段头 1 次落盘（done=0）
    - 每完成 5 个素材落 1 次（done=5、done=10）
    - 阶段尾 1 次落盘（done=12）

    本测试不真起线程池，直接调 ``_persist`` 模拟节奏；它能验证"5+5+2"边界
    被正确切分（即在哪些 done 值上落盘）。集成层的端到端验证留给 Task 8。
    """
    from tripclipper.analyzer import _persist, _PERSIST_EVERY
    from tripclipper.models import CutIndex, ProjectInfo

    cut = CutIndex(project=ProjectInfo(project_name="t", project_slug="t"))
    invocations: list[int] = []

    def record(done: int) -> None:
        invocations.append(done)

    # 模拟编排：阶段头落盘
    _persist(cut, Path("/dev/null"), done=0, callback=record)
    # 12 个素材按完成顺序累计
    for done in range(1, 13):
        if done % _PERSIST_EVERY == 0:
            _persist(cut, Path("/dev/null"), done=done, callback=record)
    # 阶段尾落盘
    _persist(cut, Path("/dev/null"), done=12, callback=record)

    # 期待落盘节奏：0（头）/ 5 / 10 / 12（尾）
    assert invocations == [0, 5, 10, 12]


# ---------------------------------------------------------------------------
# 错误归类 / 摘要（_classify_reason + _summarize_errors）
# ---------------------------------------------------------------------------


def test_classify_reason_buckets():
    assert _classify_reason("HTTP 429: rate limit") == "HTTP 429"
    assert _classify_reason("HTTP 503: bad gateway") == "HTTP 5xx"
    assert _classify_reason("ProviderTimeoutError: 60s × 3 次") == "timeout"
    assert _classify_reason("ProviderNetworkError: ConnectError") == "network"
    assert _classify_reason("非法 JSON: 解析失败") == "非法 JSON"
    assert _classify_reason("invalid json") == "非法 JSON"
    assert _classify_reason("something else entirely") == "其他"


def test_summarize_errors_empty_returns_empty_string():
    assert _summarize_errors([]) == ""


def test_summarize_errors_renders_counts_in_fixed_order():
    errors = [
        ("a1", "HTTP 429: rate"),
        ("a2", "HTTP 429: rate"),
        ("a3", "非法 JSON: bad"),
    ]
    out = _summarize_errors(errors)
    assert out.startswith("3 个素材分析失败")
    assert "2 次 HTTP 429" in out
    assert "1 次 非法 JSON" in out


# ---------------------------------------------------------------------------
# SubTask 7.8：AnalyzeLogger 脱敏白名单 —— 不写 Authorization/prompt/content
# ---------------------------------------------------------------------------


def test_logger_drops_unknown_fields_and_scrubs_error(tmp_path: Path):
    logger = AnalyzeLogger("slug-x", base_dir=tmp_path)

    # 故意传入白名单外的字段（authorization / prompt / content）+ error 含密钥。
    logger._write_event(
        "call_end",
        {
            "event": "call_end",
            "ts": "2026-06-25T00:00:00+00:00",
            "asset_id": "a1",
            "attempt": 1,
            "status": "failure",
            "http_code": 401,
            "latency_ms": 12,
            "error": (
                "ProviderError: HTTP 401: api_key=sk-LIVE-XXXX "
                "Authorization: Bearer sk-LIVE-YYYY full-prompt-here"
            ),
            "project_slug": "slug-x",
            # 以下三项**不应**出现在落盘行里：
            "authorization": "Bearer sk-LIVE-ZZZZ",
            "prompt": "你是一名严谨的旅拍素材剪辑助理...",
            "content": '{"summary": "..."}',
        },
    )

    log_text = logger.log_path.read_text(encoding="utf-8")
    assert log_text.strip(), "日志文件应当至少有一行"

    # 1) 白名单之外的键完全不应作为 JSON key 出现（key 维度判定，
    #    避免误伤 error 字段内字面值里出现的"Authorization:"字符串）。
    line = log_text.strip().splitlines()[0]
    payload = json.loads(line)
    assert "authorization" not in payload
    assert "prompt" not in payload
    assert "content" not in payload
    # 即便如此，敏感的 prompt 原文也不该出现在任何字段值里。
    assert "你是一名严谨的旅拍素材剪辑助理" not in log_text

    # 2) 密钥裸串不应出现（Bearer 与 sk- 都被脱敏为 [REDACTED]）。
    assert "sk-LIVE-XXXX" not in log_text
    assert "sk-LIVE-YYYY" not in log_text
    assert "sk-LIVE-ZZZZ" not in log_text
    assert "Bearer sk-" not in log_text

    # 3) 落盘行必备字段齐全。
    assert payload["event"] == "call_end"
    assert payload["asset_id"] == "a1"
    assert payload["attempt"] == 1
    assert payload["status"] == "failure"
    assert payload["http_code"] == 401


def test_logger_truncates_long_error(tmp_path: Path):
    logger = AnalyzeLogger("slug-x", base_dir=tmp_path)
    huge = "x" * 2000
    logger._write_event(
        "call_end",
        {
            "event": "call_end",
            "ts": "2026-06-25T00:00:00+00:00",
            "asset_id": "a1",
            "attempt": 1,
            "status": "failure",
            "error": huge,
            "project_slug": "slug-x",
        },
    )
    line = logger.log_path.read_text(encoding="utf-8").strip().splitlines()[0]
    payload = json.loads(line)
    # 截断到 512（_ERROR_FIELD_MAX_LEN），不允许 2000 全量写盘。
    assert len(payload["error"]) <= 512


def test_logger_stage_events_roundtrip(tmp_path: Path):
    logger = AnalyzeLogger("slug-y", base_dir=tmp_path)
    logger.stage_start(stage="sample", total=3, concurrency=2)
    logger.call_start(asset_id="a1", attempt=1, asset_type="video", frame_count=3)
    logger.call_end(
        asset_id="a1",
        attempt=1,
        status="success",
        http_code=200,
        latency_ms=120,
    )
    logger.stage_end(stage="sample", succeeded=1, failed=0, skipped=0, duration_ms=200)
    logger.close()

    lines = logger.log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4
    events = [json.loads(line)["event"] for line in lines]
    assert events == ["stage_start", "call_start", "call_end", "stage_end"]
