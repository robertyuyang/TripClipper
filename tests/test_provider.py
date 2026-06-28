"""M3 Provider 纯函数单元测试（Task 7：SubTask 7.1/7.2/7.6/7.7）。

测试纪律（spec Q1/Q2/Q17）：

- **零 mock / 零 monkeypatch 函数替换 / 零 stub 模型**。
- 本文件只测 ``_parse_response`` / ``_should_retry`` / ``_build_user_content``
  / ``Provider._render_system_prompt`` 这几个纯函数。喂手工字符串测
  ``_parse_response`` 不算 mock 模型——约束的是"不许伪造分析结果当真写回
  ``cut_index.json``"，不是"不许测纯函数"。
- 真打模型的 integration 测试在 Task 8（同文件后续追加或单独走 conftest）。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from tripclipper.config import EditingIntent
from tripclipper.models import (
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
    _parse_response,
    _should_retry,
)


# ---------------------------------------------------------------------------
# SubTask 7.1：_parse_response 各分支
# ---------------------------------------------------------------------------


def _valid_payload() -> dict:
    return {
        "summary": "无人机俯瞰雪山的开场镜头",
        "tags": ["雪山", "航拍", "开场"],
        "rating": 4,
        "subject_type": "landscape",
        "primary_subject": "雪山",
        "people_presence": "none",
        "shot_scale": "extreme_wide",
        "shot_function": "establishing",
        "audio_strategy": "保留环境声",
        "segments": [
            {
                "in": "00:00:01",
                "out": "00:00:05",
                "role": "开场",
                "reason": "稳定大景",
                "audio_strategy": "保留环境声",
            }
        ],
    }


def test_parse_response_happy_path():
    result = _parse_response(json.dumps(_valid_payload(), ensure_ascii=False))
    assert isinstance(result, AnalysisResult)
    assert result.summary == "无人机俯瞰雪山的开场镜头"
    assert result.tags == ["雪山", "航拍", "开场"]
    assert result.rating == 4
    assert result.subject_type == SubjectType.landscape
    assert result.primary_subject == "雪山"
    assert result.people_presence == PeoplePresence.none
    assert result.shot_scale == ShotScale.extreme_wide
    assert result.shot_function == ShotFunction.establishing
    assert result.audio_strategy == "保留环境声"
    assert len(result.segments) == 1
    seg = result.segments[0]
    assert seg.in_ == "00:00:01"
    assert seg.out == "00:00:05"
    assert seg.role == "开场"


def test_parse_response_strips_json_code_fence():
    text = "```json\n" + json.dumps(_valid_payload(), ensure_ascii=False) + "\n```"
    result = _parse_response(text)
    assert result.summary is not None
    assert result.subject_type == SubjectType.landscape


def test_parse_response_strips_bare_code_fence():
    text = "```\n" + json.dumps(_valid_payload(), ensure_ascii=False) + "\n```"
    result = _parse_response(text)
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
    assert result.segments == []


def test_parse_response_invalid_enum_degrades():
    payload = _valid_payload()
    payload["subject_type"] = "totally-not-a-subject-type"
    payload["shot_function"] = "alien-shot-function"
    payload["people_presence"] = "many-people"
    payload["shot_scale"] = "uber-wide"
    result = _parse_response(json.dumps(payload, ensure_ascii=False))
    assert result.subject_type == SubjectType.other
    assert result.shot_function == ShotFunction.other
    assert result.people_presence is None
    assert result.shot_scale is None


@pytest.mark.parametrize("bad_rating", [0, 6, -1, "abc", 3.5, True, None])
def test_parse_response_rating_out_of_range_is_none(bad_rating):
    payload = _valid_payload()
    payload["rating"] = bad_rating
    result = _parse_response(json.dumps(payload, ensure_ascii=False))
    assert result.rating is None


def test_parse_response_segments_top_level_non_list_drops_all_but_preserves_rest():
    payload = _valid_payload()
    payload["segments"] = "should-be-a-list"
    result = _parse_response(json.dumps(payload, ensure_ascii=False))
    assert result.segments == []
    # 其他字段不受影响
    assert result.summary == "无人机俯瞰雪山的开场镜头"
    assert result.rating == 4


def test_parse_response_segments_invalid_entry_dropped_others_kept():
    payload = _valid_payload()
    payload["segments"] = [
        {"in": "00:00:01", "out": "00:00:05", "role": "保留"},
        {"in": "", "out": "00:00:09"},  # in 空 → 丢
        {"in": "00:00:10"},               # 缺 out → 丢
        "not-a-dict",                     # 非 dict → 丢
        {"in": "00:00:11", "out": "00:00:15", "role": "也保留"},
    ]
    result = _parse_response(json.dumps(payload, ensure_ascii=False))
    assert len(result.segments) == 2
    assert result.segments[0].in_ == "00:00:01"
    assert result.segments[1].in_ == "00:00:11"


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
# SubTask 7.6：_build_user_content 三分叉
# ---------------------------------------------------------------------------


@pytest.fixture
def jpeg_file(tmp_path: Path) -> Path:
    """写一张最小的合法 JPEG（仅头尾两字节也够 base64 编码用）。"""
    # 真造一个超小 jpg 不是为了被解码，只是给 _image_data_url 用 open()+b64encode。
    path = tmp_path / "tiny.jpg"
    path.write_bytes(b"\xff\xd8\xff\xd9")
    return path


def test_build_user_content_video_branch(jpeg_file: Path, tmp_path: Path):
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
        metadata={"duration": 12.3, "has_audio": True},
    )
    content = _build_user_content(asset)
    image_blocks = [b for b in content if b.get("type") == "image_url"]
    text_blocks = [b for b in content if b.get("type") == "text"]
    # 1 缩略图 + 3 帧 = 4 张图（不超过 _MAX_FRAMES_FOR_PROMPT=3，加上缩略图共 4）。
    assert len(image_blocks) == 4
    for block in image_blocks:
        url = block["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")
    assert len(text_blocks) == 1
    text = text_blocks[0]["text"]
    assert "clip.mp4" in text
    assert "video" in text
    assert "12.3" in text


def test_build_user_content_video_caps_frames_at_three(jpeg_file: Path, tmp_path: Path):
    frames = []
    for idx in range(10):
        frame = tmp_path / f"frame_{idx}.jpg"
        frame.write_bytes(b"\xff\xd8\xff\xd9")
        frames.append(str(frame))
    asset = Asset(
        asset_id="a-video",
        type=AssetType.video,
        filename="long.mp4",
        thumbnail_path=str(jpeg_file),
        frame_paths=frames,
    )
    content = _build_user_content(asset)
    image_blocks = [b for b in content if b.get("type") == "image_url"]
    # 缩略图 1 + 关键帧上限 3 = 4，不应被 10 帧撑爆。
    assert len(image_blocks) == 4


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
    assert len(text_blocks) == 1
    assert image_blocks[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


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
