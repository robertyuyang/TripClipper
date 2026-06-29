"""M3 Integration 测试（Task 8：SubTask 8.1/8.2/8.3/8.4）—— 真打 cherryin
``google/gemini-3.5-flash``，零 mock、零 skipif、缺 key 直接 fail。

测试纪律（spec Q1/Q2）：

- 缺 ``TRIPCLIPPER_MODEL_API_KEY`` → 直接 ``pytest.fail``。
- 缺 ``tests/videos/<filename>`` → 直接 ``pytest.fail``。
- **不**使用 ``pytest.skipif`` / 不录制回放 / 不进 CI。
- 4 个用例真实调用 cherryin 上的 ``google/gemini-3.5-flash``，会消耗 token。
  跑一次代价低（每个用例约 1-3 张图 + 1 次推理），不要循环跑。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from tripclipper.analyzer import sample_analyze
from tripclipper.config import EditingIntent, ModelConfig
from tripclipper.cut_index import read_cut_index
from tripclipper.models import (
    AnalysisStatus,
    AssetType,
    PeoplePresence,
    ShotFunction,
    ShotScale,
    SubjectType,
)
from tripclipper.paths import cut_index_path
from tripclipper.project import init_project
from tripclipper.provider import AnalysisResult, Provider, ProviderError, _parse_timecode
from tripclipper.scan import scan_project


# ---------------------------------------------------------------------------
# 共享前置
# ---------------------------------------------------------------------------


VIDEOS_DIR = Path(__file__).resolve().parent / "videos"
SMALL_VIDEO = VIDEOS_DIR / "DJI_20260612134026_0001_D.MP4"
SEGMENTS_VIDEO = VIDEOS_DIR / "IMG_4306.mov"
PIPELINE_VIDEOS = (
    "DJI_20260612134026_0001_D.MP4",
    "DJI_20260613145058_0115_D.MP4",
    "IMG_4306.mov",
    "NO20250612-114146-064576F.mp4",
    "NO20250612-114246-064577F.mp4",
)

_PROVIDER_BASE_URL = "https://open.cherryin.ai/v1"
_VISION_MODEL = "google/gemini-3.5-flash"
_API_KEY_ENV = "TRIPCLIPPER_MODEL_API_KEY"

# 项目根的 .env 不一定已经被 pytest 进程加载——这里强制 load 一次（不覆盖已有 env）。
_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env", override=False)


def _require_api_key() -> str:
    key = os.environ.get(_API_KEY_ENV, "")
    if not key:
        pytest.fail(
            "M3 集成测试需要 .env 配置 "
            f"{_API_KEY_ENV}（缺失或为空，且本仓库禁用 pytest.skipif）"
        )
    return key


def _require_video(filename: str) -> Path:
    path = VIDEOS_DIR / filename
    if not path.is_file():
        pytest.fail(f"M3 集成测试需要 tests/videos/{filename} 存在")
    return path


def _model_config() -> ModelConfig:
    return ModelConfig(
        provider="openai_compatible",
        base_url=_PROVIDER_BASE_URL,
        api_key_env=_API_KEY_ENV,
        vision_model=_VISION_MODEL,
        text_model=_VISION_MODEL,
        language="zh-CN",
        sample_size=25,
    )


def _project_yaml(source_folder: Path) -> str:
    """渲染最小可用的 project.yaml，模型配置指向真实 cherryin。"""
    return (
        f'project_name: "M3 Integration"\n'
        f'source_folder: "{source_folder}"\n'
        'output_style: "activity_recap"\n'
        'target_length: "3min"\n'
        "model_config:\n"
        '  provider: "openai_compatible"\n'
        f'  base_url: "{_PROVIDER_BASE_URL}"\n'
        f'  api_key_env: "{_API_KEY_ENV}"\n'
        f'  vision_model: "{_VISION_MODEL}"\n'
        f'  text_model: "{_VISION_MODEL}"\n'
        '  language: "zh-CN"\n'
        '  sample_size: 5\n'
    )


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


# ---------------------------------------------------------------------------
# Helper：用 scan_project 拿到一个真实 Asset（含 thumbnail_path / frame_paths）
# ---------------------------------------------------------------------------


def _setup_single_video_project(
    tmp_path: Path, video: Path
) -> tuple[Path, str]:
    """在 ``tmp_path`` 下 symlink 一个 video，跑 init + scan，返回 (base_dir, slug)。"""
    source = tmp_path / "src"
    source.mkdir()
    (source / video.name).symlink_to(video)

    config_path = tmp_path / "project.yaml"
    config_path.write_text(_project_yaml(source), encoding="utf-8")
    base_dir = tmp_path / "projects"
    summary = init_project(config_path, base_dir=base_dir)
    scan_project(summary.project_slug, base_dir=base_dir)
    return base_dir, summary.project_slug


# ---------------------------------------------------------------------------
# SubTask 8.1：单视频真打模型
# ---------------------------------------------------------------------------


def test_provider_analyzes_video_real_model(tmp_path: Path):
    _require_api_key()
    video = _require_video(SMALL_VIDEO.name)

    base_dir, slug = _setup_single_video_project(tmp_path, video)
    cut = read_cut_index(cut_index_path(slug, base_dir))
    asset = next(a for a in cut.assets if a.filename == video.name)
    assert asset.type == AssetType.video
    assert asset.thumbnail_path and Path(asset.thumbnail_path).is_file()
    assert asset.frame_paths and all(Path(p).is_file() for p in asset.frame_paths)

    provider = Provider(_model_config(), EditingIntent())
    result = provider.analyze(asset)

    assert isinstance(result, AnalysisResult)
    # 必填字段非空 + 符合枚举
    assert result.summary and isinstance(result.summary, str)
    assert _has_cjk(result.summary), f"summary 应为中文: {result.summary!r}"
    assert isinstance(result.subject_type, SubjectType)
    assert isinstance(result.shot_scale, ShotScale)
    assert isinstance(result.shot_function, ShotFunction)
    # rating 允许 None（spec Q22 兜底），但若非空必须在 [1, 5]
    if result.rating is not None:
        assert 1 <= result.rating <= 5
    # people_presence 也允许 None，但若非空必须是 PeoplePresence
    if result.people_presence is not None:
        assert isinstance(result.people_presence, PeoplePresence)
    # tags 非空更说明模型理解了画面（不强制）
    assert isinstance(result.tags, list)


# ---------------------------------------------------------------------------
# SubTask 8.2：clip_suggestions 校验（不强制非空）
# ---------------------------------------------------------------------------


def test_provider_emits_valid_clip_suggestions_for_video(tmp_path: Path):
    _require_api_key()
    video = _require_video(SEGMENTS_VIDEO.name)

    base_dir, slug = _setup_single_video_project(tmp_path, video)
    cut = read_cut_index(cut_index_path(slug, base_dir))
    asset = next(a for a in cut.assets if a.filename == video.name)

    duration = float((asset.metadata or {}).get("duration") or 0)
    assert duration > 0, "测试素材必须有 duration 元数据"
    # frame_timestamps 长度必须与 frame_paths 长度一致（M2 自适应抽帧）。
    assert asset.frame_paths
    assert asset.frame_timestamps is not None
    assert len(asset.frame_timestamps) == len(asset.frame_paths)
    for ts in asset.frame_timestamps:
        assert 0.0 <= float(ts) <= duration

    provider = Provider(_model_config(), EditingIntent())
    result = provider.analyze(asset)

    # Q22：clip_suggestions 可为空（废片）。若非空，每段都必须有 in / out / role，
    # 且经 _parse_timecode 解析后满足 0 <= in_seconds < out_seconds <= duration。
    for suggestion in result.clip_suggestions:
        assert suggestion.in_ and isinstance(suggestion.in_, str)
        assert suggestion.out and isinstance(suggestion.out, str)
        if suggestion.role is not None:
            assert isinstance(suggestion.role, str)

        in_seconds = _parse_timecode(suggestion.in_)
        out_seconds = _parse_timecode(suggestion.out)
        assert in_seconds is not None
        assert out_seconds is not None
        assert 0.0 <= in_seconds < out_seconds
        assert out_seconds <= duration


# ---------------------------------------------------------------------------
# SubTask 8.3：端到端 sample 流水线
# ---------------------------------------------------------------------------


def test_full_pipeline_sample_real_model(tmp_path: Path):
    _require_api_key()
    for name in PIPELINE_VIDEOS:
        _require_video(name)

    # 用 symlink 在 tmp_path 下凑齐 5 个真实视频（保 tests/videos/ 只读）。
    source = tmp_path / "src"
    source.mkdir()
    for name in PIPELINE_VIDEOS:
        (source / name).symlink_to(VIDEOS_DIR / name)

    config_path = tmp_path / "project.yaml"
    config_path.write_text(_project_yaml(source), encoding="utf-8")
    base_dir = tmp_path / "projects"

    summary = init_project(config_path, base_dir=base_dir)
    scan_result = scan_project(summary.project_slug, base_dir=base_dir)
    assert scan_result.total == 5

    analyze_result = sample_analyze(
        summary.project_slug,
        base_dir=base_dir,
        concurrency=2,
    )

    # 写回的 cut_index.json 必须有 AnalysisInfo + 至少 1 个 analyzed 素材。
    cut = read_cut_index(cut_index_path(summary.project_slug, base_dir))
    assert cut.analysis is not None
    assert cut.analysis.stage == "sample"
    assert cut.analysis.status in {"completed", "partial"}
    assert cut.analysis.started_at and cut.analysis.finished_at
    assert cut.analysis.provider == "openai_compatible"
    assert cut.analysis.vision_model == _VISION_MODEL

    # 至少 1 个成功（不要求全部成功；模型偶发 JSON 不合规可能让少数失败）。
    assert analyze_result.succeeded >= 1
    assert analyze_result.total <= 5

    analyzed_assets = [
        a for a in cut.assets if a.analysis_status == AnalysisStatus.analyzed
    ]
    assert len(analyzed_assets) >= 1
    # 成功素材必须有 summary 与基本枚举字段。
    for asset in analyzed_assets:
        assert asset.summary
        assert isinstance(asset.subject_type, SubjectType)
        assert isinstance(asset.shot_scale, ShotScale)
        assert isinstance(asset.shot_function, ShotFunction)

    # error_summary：成功状态为 None；partial 状态为非空字符串。
    if cut.analysis.status == "completed":
        assert cut.analysis.error_summary is None
    else:
        assert cut.analysis.error_summary

    # 日志文件落盘检查（projects/<slug>/logs/analyze-*.jsonl）
    log_path = Path(analyze_result.log_path)
    assert log_path.is_file()
    log_text = log_path.read_text(encoding="utf-8")
    lines = log_text.strip().splitlines()
    assert lines, "日志至少 1 行"

    first = json.loads(lines[0])
    last = json.loads(lines[-1])
    assert first["event"] == "stage_start"
    assert last["event"] == "stage_end"
    events = {json.loads(line)["event"] for line in lines}
    assert "call_start" in events
    assert "call_end" in events

    # 日志中绝不出现 API key 字面值。
    api_key = os.environ[_API_KEY_ENV]
    assert api_key not in log_text
    assert "Bearer " + api_key not in log_text


# ---------------------------------------------------------------------------
# SubTask 8.4：无效 key 真打一次
# ---------------------------------------------------------------------------


def test_provider_invalid_key_real_model(tmp_path: Path, monkeypatch):
    # 此用例不依赖真实 key，但仍真打模型（用一个明显非法 key）。
    video = _require_video(SMALL_VIDEO.name)
    base_dir, slug = _setup_single_video_project(tmp_path, video)
    cut_before = read_cut_index(cut_index_path(slug, base_dir))
    asset = next(a for a in cut_before.assets if a.filename == video.name)

    # 临时 override key 为非法值。monkeypatch 仅改环境变量，不替换业务函数。
    monkeypatch.setenv(_API_KEY_ENV, "sk-invalid-xxxxxxxx")

    provider = Provider(_model_config(), EditingIntent())
    with pytest.raises(ProviderError) as excinfo:
        provider.analyze(asset)

    # 错误信息不应包含我们刚塞进去的 key 字面值（Q2：密钥不外泄）。
    err_text = str(excinfo.value)
    assert "sk-invalid-xxxxxxxx" not in err_text
    # 通常 cherryin 会返回 401/403；瞬时/非瞬时分类由 _should_retry 决定。
    # 这里只断言"被抛出"，不强求 transient 标志。

    # 断言 cut_index.json 中 asset 的分析字段仍为空（没被错误写入伪造数据）。
    cut_after = read_cut_index(cut_index_path(slug, base_dir))
    asset_after = next(a for a in cut_after.assets if a.filename == video.name)
    assert asset_after.summary is None
    assert asset_after.subject_type is None
    assert asset_after.shot_scale is None
    assert asset_after.shot_function is None
    assert asset_after.analysis_status == AnalysisStatus.scanned
