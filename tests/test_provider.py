"""M3 Provider 纯函数单元测试（Task 7：SubTask 7.1/7.2/7.6/7.7）。

测试纪律（spec Q1/Q2/Q17）：

- **零 mock / 零 monkeypatch 函数替换 / 零 stub 模型**。
- 本文件只测 ``_parse_response`` / ``_should_retry`` / ``_build_user_content``
  / ``Provider._render_system_prompt`` / ``_parse_timecode``
  / ``_format_frame_timestamp`` / ``_coerce_clip_suggestions`` 这几个纯函数。
  喂手工字符串测纯函数不算 mock 模型——约束的是"不许伪造分析结果当真写回
  ``cut_index.json``"，不是"不许测纯函数"。
- 真打模型的 integration 测试在 ``tests/test_integration_m3.py``。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tripclipper.config import EditingIntent
from tripclipper.models import (
    AnalysisStatus,
    Asset,
    AssetType,
    PeoplePresence,
    ShotFunction,
    ShotScale,
    SubjectType,
)
from tripclipper.provider import (
    AnalysisResult,
    Provider,
    ProviderError,
    _build_user_content,
    _coerce_clip_suggestions,
    _format_frame_timestamp,
    _parse_response,
    _parse_timecode,
    _should_retry,
    apply_analysis,
)


# ---------------------------------------------------------------------------
# SubTask 7.1：_parse_response 各分支
# ---------------------------------------------------------------------------


def _valid_payload() -> dict:
    return {
        "content_title": "无人机俯瞰雪山",
        "summary": "无人机俯瞰雪山的开场镜头",
        "tags": ["雪山", "航拍", "开场"],
        "rating": 4,
        "subject_type": "landscape",
        "primary_subject": "雪山",
        "people_presence": "none",
        "shot_scale": "extreme_wide",
        "shot_function": "establishing",
        "audio_strategy": "保留环境声",
        "clip_suggestions": [
            {
                "in": "00:00:01",
                "out": "00:00:05",
                "role": "开场",
                "reason": "稳定大景",
                "audio_strategy": "保留环境声",
                "subject_type": "landscape",
                "shot_scale": "extreme_wide",
                "rating": 4,
                "tags": ["雪山", "航拍"],
            }
        ],
    }


def test_parse_response_happy_path():
    result = _parse_response(json.dumps(_valid_payload(), ensure_ascii=False), duration=10.0)
    assert isinstance(result, AnalysisResult)
    assert result.content_title == "无人机俯瞰雪山"
    assert result.summary == "无人机俯瞰雪山的开场镜头"
    assert result.tags == ["雪山", "航拍", "开场"]
    assert result.rating == 4
    assert result.subject_type == SubjectType.landscape
    assert result.primary_subject == "雪山"
    assert result.people_presence == PeoplePresence.none
    assert result.shot_scale == ShotScale.extreme_wide
    assert result.shot_function == ShotFunction.establishing
    assert result.audio_strategy == "保留环境声"
    assert len(result.clip_suggestions) == 1
    seg = result.clip_suggestions[0]
    assert seg.in_ == "00:00:01"
    assert seg.out == "00:00:05"
    assert seg.role == "开场"
    assert seg.subject_type == SubjectType.landscape
    assert seg.shot_scale == ShotScale.extreme_wide
    assert seg.rating == 4
    assert seg.tags == ["雪山", "航拍"]


def test_apply_analysis_writes_content_title_to_asset():
    asset = Asset(type=AssetType.video)
    result = AnalysisResult(content_title="女孩在海边追着风筝奔跑")

    apply_analysis(asset, result)

    assert asset.content_title == "女孩在海边追着风筝奔跑"
    assert asset.analysis_status == AnalysisStatus.analyzed


def test_parse_response_strips_json_code_fence():
    text = "```json\n" + json.dumps(_valid_payload(), ensure_ascii=False) + "\n```"
    result = _parse_response(text, duration=10.0)
    assert result.summary is not None
    assert result.subject_type == SubjectType.landscape


def test_parse_response_strips_bare_code_fence():
    text = "```\n" + json.dumps(_valid_payload(), ensure_ascii=False) + "\n```"
    result = _parse_response(text, duration=10.0)
    assert result.summary is not None


def test_parse_response_invalid_json_raises_non_transient():
    with pytest.raises(ProviderError) as exc_info:
        _parse_response("not a json at all {")
    assert exc_info.value.transient is False


def test_parse_response_top_level_array_raises():
    with pytest.raises(ProviderError) as exc_info:
        _parse_response("[1, 2, 3]")
    # 顶层非 object 同样作为非法 JSON 处理（非瞬时）。
    assert exc_info.value.transient is False


def test_parse_response_missing_fields_returns_defaults():
    # 完全空对象：纯字符串字段 None / 列表空 / 枚举降级。
    result = _parse_response("{}")
    assert result.summary is None
    assert result.tags == []
    assert result.rating is None
    assert result.subject_type == SubjectType.other  # 非法降级（缺失视为非法）
    assert result.primary_subject is None
    assert result.people_presence is None  # 无 other 成员 → None
    assert result.shot_scale is None
    assert result.shot_function == ShotFunction.other
    assert result.audio_strategy is None
    assert result.clip_suggestions == []
    assert result.dropped_clip_suggestions == []


def test_parse_response_invalid_enum_degrades():
    payload = _valid_payload()
    payload["subject_type"] = "totally-not-a-subject-type"
    payload["shot_function"] = "alien-shot-function"
    payload["people_presence"] = "many-people"
    payload["shot_scale"] = "uber-wide"
    result = _parse_response(json.dumps(payload, ensure_ascii=False), duration=10.0)
    assert result.subject_type == SubjectType.other
    assert result.shot_function == ShotFunction.other
    assert result.people_presence is None
    assert result.shot_scale is None


@pytest.mark.parametrize("bad_rating", [0, 6, -1, "abc", 3.5, True, None])
def test_parse_response_rating_out_of_range_is_none(bad_rating):
    payload = _valid_payload()
    payload["rating"] = bad_rating
    result = _parse_response(json.dumps(payload, ensure_ascii=False), duration=10.0)
    assert result.rating is None


def test_parse_response_clip_suggestions_top_level_non_list_drops_all_but_preserves_rest():
    payload = _valid_payload()
    payload["clip_suggestions"] = "should-be-a-list"
    result = _parse_response(json.dumps(payload, ensure_ascii=False), duration=10.0)
    assert result.clip_suggestions == []
    # 顶层非 list 是 shape 错误，不算被丢弃条目。
    assert result.dropped_clip_suggestions == []
    # 其他字段不受影响
    assert result.summary == "无人机俯瞰雪山的开场镜头"
    assert result.rating == 4


def test_parse_response_segments_legacy_key_still_accepted():
    """模型若沿用 0.2 时代的 ``segments`` 键，仍按 clip_suggestions 处理。"""
    payload = _valid_payload()
    payload["segments"] = payload.pop("clip_suggestions")
    result = _parse_response(json.dumps(payload, ensure_ascii=False), duration=10.0)
    assert len(result.clip_suggestions) == 1
    assert result.clip_suggestions[0].in_ == "00:00:01"


# ---------------------------------------------------------------------------
# SubTask 7.2：_should_retry 分类
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status,expected", [
    (429, True),
    (500, True),
    (502, True),
    (503, True),
    (504, True),
    (400, False),
    (401, False),
    (403, False),
    (404, False),
    (200, False),
    (301, False),
])
def test_should_retry_http_statuses(status, expected):
    assert _should_retry(status) is expected


def test_should_retry_timeout_true():
    exc = httpx.ConnectTimeout("connect timeout")
    assert _should_retry(exc) is True
    exc2 = httpx.ReadTimeout("read timeout")
    assert _should_retry(exc2) is True


def test_should_retry_network_error_true():
    exc = httpx.ConnectError("connection refused")
    assert _should_retry(exc) is True


def test_should_retry_json_error_false():
    exc = json.JSONDecodeError("bad", "doc", 0)
    assert _should_retry(exc) is False


def test_should_retry_bool_is_false_not_int_branch():
    # bool 是 int 子类，但不能误判为 HTTP 状态码。
    assert _should_retry(True) is False
    assert _should_retry(False) is False


# ---------------------------------------------------------------------------
# SubTask 7.6：_build_user_content 三分叉 + 时间标注 text block
# ---------------------------------------------------------------------------


@pytest.fixture
def jpeg_file(tmp_path: Path) -> Path:
    """写一张最小的合法 JPEG（仅头尾两字节也够 base64 编码用）。"""
    path = tmp_path / "tiny.jpg"
    path.write_bytes(b"\xff\xd8\xff\xd9")
    return path


def test_build_user_content_video_branch_with_timestamps(jpeg_file: Path, tmp_path: Path):
    """视频分支：缩略图前 1 个 text + N 张关键帧各前 1 个 text + 1 个元数据 text。"""
    frames = []
    for idx in range(3):
        frame = tmp_path / f"frame_{idx}.jpg"
        frame.write_bytes(b"\xff\xd8\xff\xd9")
        frames.append(str(frame))
    asset = Asset(
        asset_id="a-video",
        type=AssetType.video,
        filename="clip.mp4",
        thumbnail_path=str(jpeg_file),
        frame_paths=frames,
        frame_timestamps=[10.5, 20.0, 30.5],
        metadata={"duration": 60.0, "has_audio": True},
    )
    content = _build_user_content(asset)
    image_blocks = [b for b in content if b.get("type") == "image_url"]
    text_blocks = [b for b in content if b.get("type") == "text"]
    # 1 缩略图 + 3 帧 = 4 张图。
    assert len(image_blocks) == 4
    for block in image_blocks:
        assert block["image_url"]["url"].startswith("data:image/jpeg;base64,")
    # 1（缩略图说明）+ 3（关键帧时间标注）+ 1（元数据）= 5 个 text block。
    assert len(text_blocks) == 5
    texts = [t["text"] for t in text_blocks]
    assert texts[0] == "缩略图：素材封面"
    assert texts[1] == "第 1 张关键帧 @ 00:10.5"
    assert texts[2] == "第 2 张关键帧 @ 00:20.0"
    assert texts[3] == "第 3 张关键帧 @ 00:30.5"
    assert "clip.mp4" in texts[4]
    assert "60.0" in texts[4]


def test_build_user_content_video_branch_interleave_order(jpeg_file: Path, tmp_path: Path):
    """time-label / image_url 必须严格交错出现（label 在前，image 紧随其后）。"""
    frames = []
    for idx in range(2):
        frame = tmp_path / f"frame_{idx}.jpg"
        frame.write_bytes(b"\xff\xd8\xff\xd9")
        frames.append(str(frame))
    asset = Asset(
        asset_id="a-video",
        type=AssetType.video,
        filename="clip.mp4",
        thumbnail_path=str(jpeg_file),
        frame_paths=frames,
        frame_timestamps=[2.0, 4.0],
        metadata={"duration": 6.0},
    )
    content = _build_user_content(asset)
    # 期望顺序：text(缩略图), image, text(第1帧标注), image, text(第2帧标注), image, text(元数据)
    types = [b["type"] for b in content]
    assert types == ["text", "image_url", "text", "image_url", "text", "image_url", "text"]


def test_build_user_content_video_no_timestamps_falls_back_to_unanchored_label(
    jpeg_file: Path, tmp_path: Path
):
    """frame_timestamps 缺失（老数据）时退化为不带 @ 的纯序号标注。"""
    frames = []
    for idx in range(2):
        frame = tmp_path / f"frame_{idx}.jpg"
        frame.write_bytes(b"\xff\xd8\xff\xd9")
        frames.append(str(frame))
    asset = Asset(
        asset_id="a-video",
        type=AssetType.video,
        filename="clip.mp4",
        thumbnail_path=str(jpeg_file),
        frame_paths=frames,
        frame_timestamps=[],
    )
    content = _build_user_content(asset)
    texts = [b["text"] for b in content if b["type"] == "text"]
    assert "第 1 张关键帧" in texts
    assert "第 2 张关键帧" in texts
    # 不含 @ 时间锚点
    for t in texts:
        assert "@" not in t or t.startswith("缩略图") is False


def test_build_user_content_video_uses_all_frames_no_cap(jpeg_file: Path, tmp_path: Path):
    """删除了 _MAX_FRAMES_FOR_PROMPT 后，asset 上有多少帧就送多少帧（M2 已封顶 12）。"""
    frames = []
    timestamps = []
    for idx in range(12):
        frame = tmp_path / f"frame_{idx}.jpg"
        frame.write_bytes(b"\xff\xd8\xff\xd9")
        frames.append(str(frame))
        timestamps.append(float(idx * 5))
    asset = Asset(
        asset_id="a-video",
        type=AssetType.video,
        filename="long.mp4",
        thumbnail_path=str(jpeg_file),
        frame_paths=frames,
        frame_timestamps=timestamps,
    )
    content = _build_user_content(asset)
    image_blocks = [b for b in content if b.get("type") == "image_url"]
    # 缩略图 1 + 12 关键帧 = 13。
    assert len(image_blocks) == 13


def test_build_user_content_image_branch(jpeg_file: Path):
    asset = Asset(
        asset_id="a-image",
        type=AssetType.image,
        filename="photo.jpg",
        thumbnail_path=str(jpeg_file),
        frame_paths=[],
    )
    content = _build_user_content(asset)
    image_blocks = [b for b in content if b.get("type") == "image_url"]
    text_blocks = [b for b in content if b.get("type") == "text"]
    assert len(image_blocks) == 1
    # "图片素材" + 元数据
    assert len(text_blocks) == 2
    texts = [t["text"] for t in text_blocks]
    assert texts[0] == "图片素材"
    assert image_blocks[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    # 图片分支不含 MM:SS.S 时间标注。
    for t in texts:
        assert "@" not in t or not t.startswith("第 ")


def test_build_user_content_audio_branch():
    asset = Asset(
        asset_id="a-audio",
        type=AssetType.audio,
        filename="track.mp3",
        metadata={"duration": 33.0, "has_audio": True},
    )
    content = _build_user_content(asset)
    image_blocks = [b for b in content if b.get("type") == "image_url"]
    text_blocks = [b for b in content if b.get("type") == "text"]
    assert image_blocks == []
    # audio 分支只有元数据 text。
    assert len(text_blocks) == 1
    text = text_blocks[0]["text"]
    assert "track.mp3" in text
    assert "audio" in text


# ---------------------------------------------------------------------------
# SubTask 7.7：_render_system_prompt 按 editing_intent 渲染
# ---------------------------------------------------------------------------


def test_render_system_prompt_all_none_no_intent_block():
    intent = EditingIntent()
    prompt = Provider._render_system_prompt(intent)
    # 全 None 时不应出现 "剪辑意图" 段落。
    assert "剪辑意图" not in prompt
    # 但模板自身的契约段必须保留。
    assert "JSON 对象" in prompt
    # clip_suggestions 关键字必须出现（验证 prompt 已升级）。
    assert "clip_suggestions" in prompt
    assert "关键帧时间标注" in prompt


def test_render_system_prompt_single_field_only_renders_that_field():
    intent = EditingIntent(output_style="activity_recap")
    prompt = Provider._render_system_prompt(intent)
    assert "剪辑意图" in prompt
    assert "output_style: activity_recap" in prompt
    # 其余四个字段不应出现
    for fname in ("target_length", "audience", "people_focus", "audio_priority"):
        assert f"{fname}:" not in prompt


def test_render_system_prompt_all_fields_rendered():
    intent = EditingIntent(
        output_style="activity_recap",
        target_length="3min",
        audience="家人朋友",
        people_focus="家庭聚焦",
        audio_priority="环境声优先",
    )
    prompt = Provider._render_system_prompt(intent)
    assert "剪辑意图" in prompt
    assert "output_style: activity_recap" in prompt
    assert "target_length: 3min" in prompt
    assert "audience: 家人朋友" in prompt
    assert "people_focus: 家庭聚焦" in prompt
    assert "audio_priority: 环境声优先" in prompt


# ---------------------------------------------------------------------------
# SubTask 7.x：_format_frame_timestamp 边界
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seconds,expected", [
    (0.0, "00:00.0"),
    (10.5, "00:10.5"),
    (59.0, "00:59.0"),
    (60.0, "01:00.0"),
    (125.0, "02:05.0"),
    (3666.7, "61:06.7"),
])
def test_format_frame_timestamp(seconds, expected):
    assert _format_frame_timestamp(seconds) == expected


# ---------------------------------------------------------------------------
# SubTask 7.x：_parse_timecode 解析多种格式
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("00:00:05", 5.0),
    ("00:00:05.5", 5.5),
    ("01:23:45", 5025.0),
    ("01:23:45.5", 5025.5),
    ("01:30", 90.0),
    ("00:30", 30.0),
    ("00:00", 0.0),
    ("30", 30.0),
    ("30.5", 30.5),
    ("0", 0.0),
    (5, 5.0),
    (5.5, 5.5),
    (0, 0.0),
])
def test_parse_timecode_valid(raw, expected):
    got = _parse_timecode(raw)
    assert got is not None
    assert got == pytest.approx(expected)


@pytest.mark.parametrize("raw", [
    "abc",
    "",
    "  ",
    "01:60:00",  # 分钟>=60 非法
    "00:00:60",  # 秒>=60 非法
    "01:60",     # MM:SS 中 SS>=60 非法
    None,
    True,
    -1,
    -0.5,
    [1, 2],
    {"in": "00:00"},
])
def test_parse_timecode_invalid(raw):
    assert _parse_timecode(raw) is None


# ---------------------------------------------------------------------------
# SubTask 7.x：_coerce_clip_suggestions 严格三条校验
# ---------------------------------------------------------------------------


def test_coerce_clip_suggestions_top_level_non_list_returns_empty():
    kept, dropped = _coerce_clip_suggestions("not a list", duration=10.0)
    assert kept == []
    assert dropped == []


def test_coerce_clip_suggestions_format_invalid_dropped():
    raw = [
        {"in": "abc", "out": "00:05", "role": "开场"},
        {"in": "00:00", "out": "00:03", "role": "保留"},
    ]
    kept, dropped = _coerce_clip_suggestions(raw, duration=10.0)
    assert len(kept) == 1
    assert kept[0].in_ == "00:00"
    assert kept[0].out == "00:03"
    assert len(dropped) == 1
    assert "格式非法" in dropped[0]


def test_coerce_clip_suggestions_order_invalid_dropped():
    raw = [
        {"in": "00:10", "out": "00:05", "role": "倒序"},
        {"in": "00:00", "out": "00:03", "role": "保留"},
    ]
    kept, dropped = _coerce_clip_suggestions(raw, duration=10.0)
    assert len(kept) == 1
    assert kept[0].in_ == "00:00"
    assert any("out<=in" in d for d in dropped)


def test_coerce_clip_suggestions_bounds_invalid_dropped():
    """duration=4.3：out=01:30 远超时长，整段丢弃。"""
    raw = [
        {"in": "00:00", "out": "01:30", "role": "越界"},
        {"in": "00:01", "out": "00:03", "role": "保留"},
    ]
    kept, dropped = _coerce_clip_suggestions(raw, duration=4.3)
    assert len(kept) == 1
    assert kept[0].in_ == "00:01"
    assert any("越界" in d for d in dropped)


def test_coerce_clip_suggestions_duration_none_skips_bounds_check():
    """duration=None 时仅校验格式与顺序，不校验边界。"""
    raw = [
        {"in": "00:00", "out": "99:99:99", "role": "无 duration 也走顺序"},  # 格式非法
        {"in": "00:00", "out": "01:30", "role": "极长但 duration 未知 → 保留"},
    ]
    kept, _ = _coerce_clip_suggestions(raw, duration=None)
    assert len(kept) == 1
    assert kept[0].role == "极长但 duration 未知 → 保留"


def test_coerce_clip_suggestions_all_invalid_returns_empty_kept_with_drops():
    raw = [
        {"in": "abc", "out": "def"},
        {"in": "00:10", "out": "00:05"},
        {"in": "00:00", "out": "99:99"},  # 格式非法（秒>=60）
    ]
    kept, dropped = _coerce_clip_suggestions(raw, duration=4.3)
    assert kept == []
    assert len(dropped) == 3


def test_coerce_clip_suggestions_segment_level_4_fields_populated():
    raw = [
        {
            "in": "00:00",
            "out": "00:03",
            "role": "保留",
            "subject_type": "landscape",
            "shot_scale": "wide",
            "rating": 4,
            "tags": ["雪山"],
        }
    ]
    kept, dropped = _coerce_clip_suggestions(raw, duration=10.0)
    assert len(kept) == 1
    seg = kept[0]
    assert seg.subject_type == SubjectType.landscape
    assert seg.shot_scale == ShotScale.wide
    assert seg.rating == 4
    assert seg.tags == ["雪山"]
    assert dropped == []


def test_coerce_clip_suggestions_segment_level_invalid_enum_degrades_but_keeps_segment():
    """段级 4 字段非法时整段仍保留（时间码合法）；非法枚举降级为 None。"""
    raw = [
        {
            "in": "00:00",
            "out": "00:03",
            "subject_type": "外星人",
            "shot_scale": "uber-wide",
            "rating": 99,
            "tags": "not-a-list",
        }
    ]
    kept, dropped = _coerce_clip_suggestions(raw, duration=10.0)
    assert len(kept) == 1
    seg = kept[0]
    assert seg.subject_type is None
    assert seg.shot_scale is None
    assert seg.rating is None
    assert seg.tags == []
    assert dropped == []
