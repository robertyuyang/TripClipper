"""M4 Task 8 单元测试：``arbiter._parse_arbitration`` 纯函数（SubTask 8.11）。

测试纪律（spec Q1/Q2/Q17）：

- **零 mock 模型**。这里只对 ``_parse_arbitration`` 这个纯函数喂手工构造的字符串
  做断言，不调用任何 ``Arbiter.arbitrate`` 网络方法、不打 ``httpx``。
- 喂手工字符串测纯函数不算 mock 模型——约束的是"不许伪造分析结果当真写回
  ``cut_index.json``"，不是"不许测纯函数"。
- 真打 cherryin 的集成测试在 Task 9（``tests/test_integration_m4.py``）覆盖。

末尾追加 SubTask 9.1 ``test_arbiter_real_model``：直接对 demo-scan 三条天然连号
样本（NO20250612-114146/114246/114346）跑一次真实组级仲裁，验证返回字段满足 spec
契约。**真打 cherryin 上的 ``google/gemini-3.5-flash``**，缺 key 直接 fail，不许 skip。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from dotenv import load_dotenv

from tripclipper.arbiter import (
    Arbiter,
    ArbiterError,
    ArbitrationResult,
    _parse_arbitration,
)
from tripclipper.config import load_config
from tripclipper.cut_index import read_cut_index
from tripclipper.models import AnalysisStatus, Asset
from tripclipper.paths import cut_index_path


_VALID_IDS: set[str] = {"a1", "a2", "a3"}


def _legal_payload(**overrides) -> str:
    payload = {
        "primary_asset_id": "a1",
        "alternate_asset_ids": ["a2"],
        "rejected_asset_ids": ["a3"],
        "confidence": 0.85,
        "basis": ["相近构图"],
        "reason_by_asset": {
            "a1": "构图最完整",
            "a2": "轻微抖动",
            "a3": "主体被遮挡",
        },
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# SubTask 8.11：_parse_arbitration 6+ 场景
# ---------------------------------------------------------------------------


def test_parse_legal_json_returns_correct_fields():
    result = _parse_arbitration(_legal_payload(), _VALID_IDS)
    assert isinstance(result, ArbitrationResult)
    assert result.primary_asset_id == "a1"
    assert result.alternate_asset_ids == ["a2"]
    assert result.rejected_asset_ids == ["a3"]
    assert result.confidence == 0.85
    assert result.basis == ["相近构图"]
    assert result.reason_by_asset == {
        "a1": "构图最完整",
        "a2": "轻微抖动",
        "a3": "主体被遮挡",
    }
    assert result.needs_review is False


def test_parse_invalid_json_raises_arbiter_error_non_transient():
    with pytest.raises(ArbiterError) as excinfo:
        _parse_arbitration("not a json", _VALID_IDS)
    assert excinfo.value.transient is False


def test_parse_top_level_array_raises_arbiter_error():
    with pytest.raises(ArbiterError) as excinfo:
        _parse_arbitration("[1,2,3]", _VALID_IDS)
    assert excinfo.value.transient is False


def test_parse_primary_outside_group_sets_none_and_needs_review():
    payload = _legal_payload(primary_asset_id="not_in_group")
    result = _parse_arbitration(payload, _VALID_IDS)
    assert result.primary_asset_id is None
    assert result.needs_review is True


def test_parse_alternate_outside_group_filtered():
    payload = _legal_payload(alternate_asset_ids=["a2", "ghost_id"])
    result = _parse_arbitration(payload, _VALID_IDS)
    assert "ghost_id" not in result.alternate_asset_ids
    assert "a2" in result.alternate_asset_ids
    # 含外部 id 仍触发 needs_review（spec Q5 防幻觉）。
    assert result.needs_review is True


def test_parse_rejected_outside_group_filtered():
    payload = _legal_payload(rejected_asset_ids=["a3", "ghost_id"])
    result = _parse_arbitration(payload, _VALID_IDS)
    assert "ghost_id" not in result.rejected_asset_ids
    assert "a3" in result.rejected_asset_ids
    assert result.needs_review is True


def test_parse_low_confidence_triggers_needs_review():
    payload = _legal_payload(confidence=0.4)
    result = _parse_arbitration(payload, _VALID_IDS)
    assert result.confidence == 0.4
    assert result.needs_review is True


def test_parse_missing_confidence_resets_to_zero_and_needs_review():
    payload_dict = {
        "primary_asset_id": "a1",
        "alternate_asset_ids": ["a2"],
        "rejected_asset_ids": ["a3"],
        "basis": ["相近构图"],
        "reason_by_asset": {"a1": "理由"},
    }
    result = _parse_arbitration(
        json.dumps(payload_dict, ensure_ascii=False), _VALID_IDS
    )
    assert result.confidence == 0.0
    assert result.needs_review is True


def test_parse_invalid_confidence_type_resets_to_zero_and_needs_review():
    payload = _legal_payload(confidence="high")
    result = _parse_arbitration(payload, _VALID_IDS)
    assert result.confidence == 0.0
    assert result.needs_review is True


def test_parse_out_of_range_confidence_resets_to_zero_and_needs_review():
    payload = _legal_payload(confidence=1.5)
    result = _parse_arbitration(payload, _VALID_IDS)
    assert result.confidence == 0.0
    assert result.needs_review is True


def test_parse_basis_all_invalid_filters_to_empty_and_needs_review():
    payload = _legal_payload(basis=["乱写", "更乱写"])
    result = _parse_arbitration(payload, _VALID_IDS)
    assert result.basis == []
    assert result.needs_review is True


def test_parse_basis_partially_invalid_keeps_legal_only():
    payload = _legal_payload(basis=["相近构图", "不在枚举里"])
    result = _parse_arbitration(payload, _VALID_IDS)
    assert result.basis == ["相近构图"]
    # 含至少一项合法 basis → 不因 basis 过空触发 needs_review；
    # 其余字段都合法所以整体也不应 needs_review。
    assert result.needs_review is False


def test_parse_primary_null_triggers_needs_review():
    payload = _legal_payload(primary_asset_id=None)
    result = _parse_arbitration(payload, _VALID_IDS)
    assert result.primary_asset_id is None
    assert result.needs_review is True


def test_parse_basis_non_list_treated_as_empty_and_needs_review():
    payload = _legal_payload(basis="相近构图")
    result = _parse_arbitration(payload, _VALID_IDS)
    assert result.basis == []
    assert result.needs_review is True


def test_parse_reason_by_asset_filters_out_unknown_keys():
    payload = _legal_payload(
        reason_by_asset={
            "a1": "理由 A",
            "ghost": "应被过滤",
        }
    )
    result = _parse_arbitration(payload, _VALID_IDS)
    assert "ghost" not in result.reason_by_asset
    assert result.reason_by_asset.get("a1") == "理由 A"


# ---------------------------------------------------------------------------
# SubTask 9.1：真打 cherryin 的组级仲裁集成
# ---------------------------------------------------------------------------


_DEMO_SLUG = "demo-scan"
_API_KEY_ENV = "TRIPCLIPPER_MODEL_API_KEY"
_BASIS_ENUM = {
    "同一景点", "同一动作", "相近构图", "相近画面内容", "相近声音内容",
}
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_CONNECTED_FILENAMES = (
    "NO20250612-114146-064576F.mp4",
    "NO20250612-114246-064577F.mp4",
    "NO20250612-114346-064578F.mp4",
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEMO_PROJECT_DIR = _REPO_ROOT / "projects" / _DEMO_SLUG
_DEMO_BASE_DIR = _REPO_ROOT / "projects"

# 项目根的 .env 不一定已经被 pytest 进程加载——这里强制 load 一次（不覆盖已有 env）。
load_dotenv(_REPO_ROOT / ".env", override=False)


def _require_api_key_m4() -> str:
    key = os.environ.get(_API_KEY_ENV, "")
    if not key:
        pytest.fail(
            "M4 集成测试需要 .env 配置 "
            f"{_API_KEY_ENV}（缺失或为空，且本仓库禁用 pytest.skipif）"
        )
    return key


def _require_demo_scan_ready():
    """demo-scan 必须存在且 ``analysis.status == "completed"``。"""
    if not _DEMO_PROJECT_DIR.is_dir():
        pytest.fail(
            f"M4 集成测试需要 {_DEMO_PROJECT_DIR} 存在；"
            "请先运行 `tripclipper run demo-scan` 把 analysis 跑完"
        )
    cut_path = cut_index_path(_DEMO_SLUG, _DEMO_BASE_DIR)
    if not cut_path.is_file():
        pytest.fail(f"M4 集成测试需要 {cut_path} 存在")
    cut = read_cut_index(cut_path)
    if cut.analysis is None or cut.analysis.status != "completed":
        status = cut.analysis.status if cut.analysis else None
        pytest.fail(
            f"M4 集成测试需要 demo-scan 的 analysis.status='completed'（当前 status={status}）；"
            "请先运行 `tripclipper analyze demo-scan --stage full`"
        )
    if not cut.assets:
        pytest.fail(f"M4 集成测试需要 demo-scan 的 cut.assets 非空")
    return cut


def _pick_connected_assets(cut) -> list[Asset]:
    """从 demo-scan 中按文件名挑出三条连号样本。"""
    by_filename = {a.filename: a for a in cut.assets if a.filename}
    by_relpath = {a.relative_path: a for a in cut.assets if a.relative_path}
    selected: list[Asset] = []
    for filename in _CONNECTED_FILENAMES:
        asset = by_filename.get(filename) or by_relpath.get(filename)
        if asset is None:
            pytest.fail(
                f"M4 集成测试需要 demo-scan 的 cut.assets 中存在 {filename}"
            )
        if not asset.thumbnail_path:
            pytest.fail(
                f"M4 集成测试需要 {filename} 有 thumbnail_path（请先 scan）"
            )
        if not Path(asset.thumbnail_path).is_file():
            pytest.fail(
                f"M4 集成测试需要 {filename} 的缩略图文件 {asset.thumbnail_path} 落盘存在"
            )
        if asset.analysis_status != AnalysisStatus.analyzed:
            pytest.fail(
                f"M4 集成测试需要 {filename} 的 analysis_status='analyzed'"
                f"（当前 {asset.analysis_status}）"
            )
        if asset.subject_type is None or asset.shot_scale is None:
            pytest.fail(
                f"M4 集成测试需要 {filename} 的 subject_type/shot_scale 非空"
            )
        selected.append(asset)
    return selected


def test_arbiter_real_model():
    """SubTask 9.1：真打 cherryin 的 google/gemini-3.5-flash，仲裁三条连号样本。

    断言：
    - ``primary_asset_id`` ∈ {None} ∪ 三条样本 id；
    - ``confidence`` ∈ [0, 1]；
    - ``primary_asset_id`` 非 None 时，``basis`` ⊆ 五选项枚举；
    - ``reason_by_asset`` 每条 reason 含至少一个 CJK 字符。
    """
    _require_api_key_m4()
    cut = _require_demo_scan_ready()
    group_assets = _pick_connected_assets(cut)
    assert len(group_assets) == 3

    # 与 cluster_runner 一致：从 project.yaml 读 ModelConfig + EditingIntent，
    # 不在测试里硬编码模型配置。
    config_path = cut.project.config_path
    assert config_path, "demo-scan/cut_index.json 缺少 project.config_path"
    project_config = load_config(config_path)
    assert project_config.llm.is_usable(), (
        "demo-scan/project.yaml 的 model_config 不可用，"
        "需要 provider/base_url/api_key_env/vision_model 齐全"
    )

    arbiter = Arbiter(project_config.llm, project_config.editing_intent)
    result = arbiter.arbitrate(group_assets)

    assert isinstance(result, ArbitrationResult)

    valid_ids = {a.asset_id for a in group_assets}
    # primary 要么 None（needs_review），要么落在三条素材里。
    assert result.primary_asset_id is None or result.primary_asset_id in valid_ids

    assert isinstance(result.confidence, float)
    assert 0.0 <= result.confidence <= 1.0

    if result.primary_asset_id is not None:
        # 真模型应输出至少一项合法 basis；且全部 basis 必须落在五选项内。
        for item in result.basis:
            assert item in _BASIS_ENUM, f"basis 越界：{item!r}"

    # reason_by_asset 的每条 value 必须含 CJK 字符（spec 强制中文）。
    for asset_id, reason in result.reason_by_asset.items():
        assert asset_id in valid_ids, f"reason_by_asset 出现组外 id：{asset_id!r}"
        assert isinstance(reason, str) and reason
        assert _CJK_RE.search(reason), f"reason 应为中文，实际：{reason!r}"
