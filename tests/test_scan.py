"""M2 本地素材扫描（Stage 1）测试 —— 零 mock 的真实集成测试。

测试原则（与 spec/task_list 一致）：
- **不使用任何 mock / monkeypatch 函数替换 / stub**；``ffmpeg``/``ffprobe``
  必须真实安装并被真实调用（本机 ``/opt/homebrew/bin`` 8.1.2）。运行前请确保
  ``PATH`` 含该目录。
- **媒体素材来源 = 仓库本地 ``tests/videos/`` 下用户提供的真实视频**，全量参与
  扫描，不自造媒体。本期**只测视频**。
- 为保持 ``tests/videos/`` 只读且不被合成文件污染，凡需要叠加非媒体/损坏文件的
  用例，都在 ``tmp_path`` 下新建源目录，并以 **symlink** 指向真实视频（避免拷贝
  约 1GB），再写入合成的非媒体/垃圾文件。
- **降级分支用真实空 PATH 触发**（``monkeypatch.setenv("PATH", <空目录>)`` 只改
  环境变量，不替换任何函数行为）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from tripclipper.cli import main
from tripclipper.cut_index import read_cut_index, write_cut_index
from tripclipper.models import AnalysisStatus, AssetType
from tripclipper.paths import cut_index_path, frames_dir, thumbnails_dir
from tripclipper.project import init_project
from tripclipper.scan import (
    SUPPORTED_EXTENSIONS,
    ScanError,
    ScanResult,
    build_asset,
    classify_file,
    detect_capabilities,
    scan_project,
)

# ---------------------------------------------------------------------------
# 真实素材与项目前置
# ---------------------------------------------------------------------------

VIDEOS_DIR = Path(__file__).resolve().parent / "videos"
# 最小的真实视频（约 23MB），用于需要"少量但真实"素材的快速用例。
SMALL_VIDEO = VIDEOS_DIR / "DJI_20260612134026_0001_D.MP4"

PROJECT_NAME = "M2 Scan Test"
SLUG = "m2-scan-test"


def _project_yaml(source_folder: Path) -> str:
    """渲染一份可被 load_config 解析的最小 project.yaml（含完整 model_config）。"""
    return (
        f'project_name: "{PROJECT_NAME}"\n'
        f'source_folder: "{source_folder}"\n'
        'output_style: "activity_recap"\n'
        'target_length: "3min"\n'
        "model_config:\n"
        '  provider: "openai_compatible"\n'
        '  base_url: "https://api.example.com/v1"\n'
        '  api_key_env: "TRIPCLIPPER_MODEL_API_KEY"\n'
        '  vision_model: "vision-model-name"\n'
    )


def _setup_project(tmp_path: Path, source_folder: Path) -> tuple[Path, Path]:
    """写 project.yaml 并用 M1 ``init_project`` 真实初始化项目。

    返回 ``(config_path, base_dir)``；项目 slug 固定为 :data:`SLUG`。
    """
    config_path = tmp_path / "project.yaml"
    config_path.write_text(_project_yaml(source_folder), encoding="utf-8")
    base_dir = tmp_path / "projects"
    init_project(config_path, base_dir=base_dir)
    return config_path, base_dir


def _symlink_source(tmp_path: Path, links: dict[str, Path]) -> Path:
    """在 ``tmp_path`` 下建一个源目录，用 symlink 指向真实视频（保持 tests/videos 只读）。

    ``links`` 形如 ``{"a.MP4": SMALL_VIDEO}``。返回该源目录。
    """
    source = tmp_path / "src"
    source.mkdir()
    for name, target in links.items():
        (source / name).symlink_to(target)
    return source


def _by_filename(cut) -> dict:
    """把 cut_index 的 assets 按 filename 索引，便于按真值断言。"""
    return {a.filename: a for a in cut.assets}


# ---------------------------------------------------------------------------
# 模块级：对真实 8 个视频跑一次完整扫描（含抽帧），多用例共享结果
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_scan(tmp_path_factory: pytest.TempPathFactory):
    """对 ``tests/videos/`` 全部真实视频跑一次完整扫描（含缩略图/关键帧）。

    返回 ``(result, cut, base_dir, slug)``。模块作用域，只执行一次。
    """
    base_tmp = tmp_path_factory.mktemp("realbase")
    config_path = base_tmp / "project.yaml"
    config_path.write_text(_project_yaml(VIDEOS_DIR), encoding="utf-8")
    base_dir = base_tmp / "projects"
    init_project(config_path, base_dir=base_dir)

    result = scan_project(SLUG, base_dir=base_dir, extract_media=True)
    cut = read_cut_index(cut_index_path(SLUG, base_dir=base_dir))
    return result, cut, base_dir, SLUG


# ---------------------------------------------------------------------------
# 纯函数：常量与分类（无需外部工具）
# ---------------------------------------------------------------------------


def test_supported_extensions_cover_td5_types() -> None:
    assert SUPPORTED_EXTENSIONS[".mp4"] == AssetType.video
    assert SUPPORTED_EXTENSIONS[".jpg"] == AssetType.image
    assert SUPPORTED_EXTENSIONS[".mp3"] == AssetType.audio
    # 键统一小写。
    assert all(k == k.lower() for k in SUPPORTED_EXTENSIONS)


def test_classify_file_case_insensitive() -> None:
    assert classify_file("a.MP4") == AssetType.video
    assert classify_file("a.mp4") == AssetType.video
    assert classify_file("a.JPG") == AssetType.image
    assert classify_file("note.txt") is None
    assert classify_file("README") is None


def test_detect_capabilities_real_env() -> None:
    """真实环境（PATH 含 ffmpeg/ffprobe）下应判定为可用。"""
    cap = detect_capabilities()
    assert cap.ffmpeg is True
    assert cap.ffprobe is True
    assert cap.notes


# ---------------------------------------------------------------------------
# 6.1 / 6.2 递归发现 + 大小写不敏感
# ---------------------------------------------------------------------------


def test_discovers_all_real_videos(real_scan) -> None:
    result, cut, _base, _slug = real_scan
    # tests/videos 有 8 个视频（4 个 .mp4 + 4 个 .MP4），全部 type=video。
    assert result.total == 8
    assert result.by_type["video"] == 8
    assert result.by_type["image"] == 0
    assert result.by_type["audio"] == 0
    assert len(cut.assets) == 8
    assert all(a.type == AssetType.video for a in cut.assets)
    # 大小写不敏感：大写 .MP4 与小写 .mp4 都被识别。
    exts = {a.extension for a in cut.assets}
    assert exts == {".mp4"}  # extension 统一小写


def test_non_media_skipped(tmp_path: Path) -> None:
    source = _symlink_source(tmp_path, {"clip.MP4": SMALL_VIDEO})
    (source / "note.txt").write_text("hello", encoding="utf-8")
    (source / "README").write_text("no extension", encoding="utf-8")
    sub = source / "docs"
    sub.mkdir()
    (sub / "guide.docx").write_text("x", encoding="utf-8")

    _config, base = _setup_project(tmp_path, source)
    result = scan_project(SLUG, base_dir=base, extract_media=True)

    assert result.total == 1
    assert result.by_type["video"] == 1
    # note.txt / README / guide.docx 三个非媒体被跳过。
    assert result.skipped == 3


# ---------------------------------------------------------------------------
# 6.3 基础信息齐全 + 稳定 asset_id + 排序
# ---------------------------------------------------------------------------


def test_base_info_complete_and_sorted(real_scan) -> None:
    _result, cut, _base, _slug = real_scan
    for a in cut.assets:
        assert a.asset_id and a.asset_id.startswith("asset_")
        assert a.filename
        assert a.path and Path(a.path).is_absolute()
        assert a.relative_path
        assert a.extension == ".mp4"
        assert isinstance(a.size, int) and a.size > 0
        assert a.modified_time
        assert a.analysis_status == AnalysisStatus.scanned
    # assets 按相对路径排序（确定性）。
    rels = [a.relative_path for a in cut.assets]
    assert rels == sorted(rels)


def test_asset_id_stable_across_scans(tmp_path: Path) -> None:
    source = _symlink_source(tmp_path, {"clip.MP4": SMALL_VIDEO})
    _config, base = _setup_project(tmp_path, source)

    scan_project(SLUG, base_dir=base, extract_media=False)
    cut1 = read_cut_index(cut_index_path(SLUG, base_dir=base))
    id1 = cut1.assets[0].asset_id

    scan_project(SLUG, base_dir=base, extract_media=False)
    cut2 = read_cut_index(cut_index_path(SLUG, base_dir=base))
    id2 = cut2.assets[0].asset_id

    assert id1 == id2
    # build_asset 单独调用也得到同一 ID（复用 M0 generate_asset_id）。
    standalone = build_asset(source / "clip.MP4", source)
    assert standalone.asset_id == id1


# ---------------------------------------------------------------------------
# 6.4 真实 ffprobe 元数据贴合实测真值（主流选择 + 分数帧率）+ 真实抽帧
# ---------------------------------------------------------------------------


def test_metadata_matches_probe_truth(real_scan) -> None:
    _result, cut, _base, _slug = real_scan
    assets = _by_filename(cut)

    # DJI 最小文件：主流 1920×1080 hevc，忽略 mjpeg(1280×720) 封面与 data 流；
    # 分数帧率 60000/1001 → 59.94；含音轨；时长约 4.33s。
    dji = assets["DJI_20260612134026_0001_D.MP4"].metadata
    assert dji["width"] == 1920
    assert dji["height"] == 1080
    assert dji["codec"] == "hevc"
    assert dji["fps"] == 59.94
    assert isinstance(dji["fps"], float)
    assert dji["has_audio"] is True
    assert 4.0 < dji["duration"] < 5.0

    # NO 系列：主流 1920×1080，忽略 640×480 h264 副流；帧率 30/1 → 30.0；约 60s。
    no = assets["NO20250612-114146-064576F.mp4"].metadata
    assert no["width"] == 1920
    assert no["height"] == 1080
    assert no["codec"] == "hevc"
    assert no["fps"] == 30.0
    assert no["has_audio"] is True
    assert 59.0 < no["duration"] < 61.0

    # DJI 2688×1512 系列：主流取大分辨率。
    dji_2688 = assets["DJI_20260613145058_0115_D.MP4"].metadata
    assert dji_2688["width"] == 2688
    assert dji_2688["height"] == 1512
    assert dji_2688["fps"] == 59.94


def test_thumbnails_and_frames_extracted(real_scan) -> None:
    _result, cut, base, slug = real_scan
    tdir = thumbnails_dir(slug, base_dir=base)
    fdir = frames_dir(slug, base_dir=base)

    for a in cut.assets:
        # 缩略图回填且真实落盘于 cache/thumbnails。
        assert a.thumbnail_path
        thumb = Path(a.thumbnail_path)
        assert thumb.is_file()
        assert tdir in thumb.parents
        # 至多 3 帧关键帧，真实落盘于 cache/frames。
        assert 1 <= len(a.frame_paths) <= 3
        for fp in a.frame_paths:
            frame = Path(fp)
            assert frame.is_file()
            assert fdir in frame.parents


# ---------------------------------------------------------------------------
# 6.5 真实空 PATH → 优雅降级（不崩溃，基础信息仍写入）
# ---------------------------------------------------------------------------


def test_graceful_degradation_empty_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _symlink_source(tmp_path, {"clip.MP4": SMALL_VIDEO})
    _config, base = _setup_project(tmp_path, source)

    # 真实地把 PATH 指向一个空目录，让 shutil.which 真实找不到工具。
    empty = tmp_path / "empty_bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    result = scan_project(SLUG, base_dir=base, extract_media=True)

    assert result.capabilities.ffmpeg is False
    assert result.capabilities.ffprobe is False
    assert result.total == 1

    cut = read_cut_index(cut_index_path(SLUG, base_dir=base))
    asset = cut.assets[0]
    # 基础信息仍写入。
    assert asset.asset_id
    assert asset.size and asset.size > 0
    # 无媒体信息与缩略图/关键帧。
    assert asset.metadata == {}
    assert asset.thumbnail_path is None
    assert asset.frame_paths == []
    # 含一条 stage=scan 的能力警告。
    cap_warnings = [
        w for w in cut.warnings if w.stage == "scan" and "ffmpeg/ffprobe" in (w.reason or "")
    ]
    assert cap_warnings
    assert all(w.blocking is False for w in cap_warnings)


# ---------------------------------------------------------------------------
# 6.6 单文件失败隔离（真实 ffprobe 在损坏 .mp4 上失败）
# ---------------------------------------------------------------------------


def test_single_file_failure_isolation(tmp_path: Path) -> None:
    source = _symlink_source(tmp_path, {"good.MP4": SMALL_VIDEO})
    # 真实垃圾字节的 .mp4：让真实 ffprobe/ffmpeg 真实失败。
    (source / "broken.mp4").write_bytes(b"not a real mp4 file" * 100)

    _config, base = _setup_project(tmp_path, source)
    result = scan_project(SLUG, base_dir=base, extract_media=True)

    # 两个文件都识别为 video 并进入 assets。
    assert result.by_type["video"] == 2
    assert result.failures >= 1

    cut = read_cut_index(cut_index_path(SLUG, base_dir=base))
    assets = _by_filename(cut)

    good = assets["good.MP4"]
    assert good.metadata.get("width") == 1920
    assert good.thumbnail_path

    broken = assets["broken.mp4"]
    # 损坏文件仍以基础信息入 assets，并记录失败。
    assert broken.asset_id
    assert broken.size and broken.size > 0
    assert broken.failures


# ---------------------------------------------------------------------------
# 6.7 空目录提示
# ---------------------------------------------------------------------------


def test_empty_source_warns(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    _config, base = _setup_project(tmp_path, source)

    result = scan_project(SLUG, base_dir=base, extract_media=True)

    assert result.total == 0
    assert result.is_empty is True

    cut = read_cut_index(cut_index_path(SLUG, base_dir=base))
    assert cut.assets == []
    empty_warnings = [
        w for w in cut.warnings if w.stage == "scan" and "未发现可处理媒体" in (w.reason or "")
    ]
    assert empty_warnings
    assert all(w.blocking is False for w in empty_warnings)


# ---------------------------------------------------------------------------
# 6.8 幂等保活 + 重复扫描不报错 + 源消失警告
# ---------------------------------------------------------------------------


def test_rescan_preserves_analysis_and_adds_new(tmp_path: Path) -> None:
    source = _symlink_source(tmp_path, {"a.MP4": SMALL_VIDEO})
    _config, base = _setup_project(tmp_path, source)
    index = cut_index_path(SLUG, base_dir=base)

    # 第一次扫描。
    scan_project(SLUG, base_dir=base, extract_media=False)
    cut = read_cut_index(index)
    first = cut.assets[0]
    first_id = first.asset_id
    first_size = first.size

    # 注入 Stage 2 分析字段并标记为 analyzed。
    first.summary = "keep-me"
    first.tags = ["holiday"]
    first.rating = 5
    first.analysis_status = AnalysisStatus.analyzed
    write_cut_index(index, cut)

    # 新增一个文件后再次扫描。
    (source / "b.MP4").symlink_to(SMALL_VIDEO)
    scan_project(SLUG, base_dir=base, extract_media=False)

    after = read_cut_index(index)
    assets = {a.asset_id: a for a in after.assets}
    assert len(after.assets) == 2

    preserved = assets[first_id]
    # Stage 2 分析字段保留。
    assert preserved.summary == "keep-me"
    assert preserved.tags == ["holiday"]
    assert preserved.rating == 5
    # 已 analyzed 不回退到 scanned。
    assert preserved.analysis_status == AnalysisStatus.analyzed
    # 文件级字段刷新（size 仍为真实大小）。
    assert preserved.size == first_size

    # 新文件作为新 asset 加入，初始 scanned。
    new_assets = [a for a in after.assets if a.asset_id != first_id]
    assert len(new_assets) == 1
    assert new_assets[0].analysis_status == AnalysisStatus.scanned


def test_rescan_twice_no_error(tmp_path: Path) -> None:
    source = _symlink_source(tmp_path, {"a.MP4": SMALL_VIDEO})
    _config, base = _setup_project(tmp_path, source)

    r1 = scan_project(SLUG, base_dir=base, extract_media=False)
    r2 = scan_project(SLUG, base_dir=base, extract_media=False)

    assert isinstance(r1, ScanResult) and isinstance(r2, ScanResult)
    assert r1.total == r2.total == 1
    cut1 = read_cut_index(cut_index_path(SLUG, base_dir=base))
    # asset_id 稳定、顺序一致。
    assert [a.relative_path for a in cut1.assets] == sorted(
        a.relative_path for a in cut1.assets
    )


def test_vanished_source_asset_is_warned_not_deleted(tmp_path: Path) -> None:
    source = _symlink_source(
        tmp_path, {"a.MP4": SMALL_VIDEO, "b.MP4": SMALL_VIDEO}
    )
    _config, base = _setup_project(tmp_path, source)
    index = cut_index_path(SLUG, base_dir=base)

    scan_project(SLUG, base_dir=base, extract_media=False)
    cut = read_cut_index(index)
    assert len(cut.assets) == 2

    # 删除其中一个源文件后再次扫描。
    (source / "b.MP4").unlink()
    scan_project(SLUG, base_dir=base, extract_media=False)

    after = read_cut_index(index)
    # 旧 asset 不被删除（仍保留 2 个）。
    assert len(after.assets) == 2
    missing_warnings = [
        w for w in after.warnings if w.stage == "scan" and "已不存在" in (w.reason or "")
    ]
    assert missing_warnings


# ---------------------------------------------------------------------------
# 6.9 源目录只读（扫描前后 tests/videos 不变；派生产物只在 cache）
# ---------------------------------------------------------------------------


def _snapshot(d: Path) -> dict[str, tuple[int, int]]:
    return {
        p.name: (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(d.iterdir())
        if p.is_file()
    }


def test_source_is_read_only(tmp_path: Path) -> None:
    before = _snapshot(VIDEOS_DIR)

    config_path = tmp_path / "project.yaml"
    config_path.write_text(_project_yaml(VIDEOS_DIR), encoding="utf-8")
    base = tmp_path / "projects"
    init_project(config_path, base_dir=base)
    scan_project(SLUG, base_dir=base, extract_media=True)

    after = _snapshot(VIDEOS_DIR)
    # 扫描前后源目录文件数量/大小/修改时间完全不变。
    assert before == after

    # 派生产物只落在项目 cache/ 下。
    assert any(thumbnails_dir(SLUG, base_dir=base).iterdir())
    assert any(frames_dir(SLUG, base_dir=base).iterdir())


# ---------------------------------------------------------------------------
# 6.10 CLI（CliRunner）
# ---------------------------------------------------------------------------


def test_cli_scan_success(tmp_path: Path) -> None:
    source = _symlink_source(tmp_path, {"clip.MP4": SMALL_VIDEO})
    config_path, base = _setup_project(tmp_path, source)

    result = CliRunner().invoke(
        main,
        [
            "analyze",
            "--stage",
            "scan",
            "--config",
            str(config_path),
            "--base-dir",
            str(base),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "扫描完成" in result.output
    assert "发现媒体总数" in result.output


def test_cli_scan_uninitialized_fails(tmp_path: Path) -> None:
    # 写 config 但不 init_project：项目无 cut_index.json。
    source = tmp_path / "src"
    source.mkdir()
    config_path = tmp_path / "project.yaml"
    config_path.write_text(_project_yaml(source), encoding="utf-8")
    base = tmp_path / "projects"

    result = CliRunner().invoke(
        main,
        [
            "analyze",
            "--stage",
            "scan",
            "--config",
            str(config_path),
            "--base-dir",
            str(base),
        ],
    )

    assert result.exit_code != 0
    assert "失败" in result.output or "init" in result.output
    # 未抛未捕获的应用异常（CliRunner 只记录 SystemExit）。
    assert not isinstance(result.exception, ScanError)
