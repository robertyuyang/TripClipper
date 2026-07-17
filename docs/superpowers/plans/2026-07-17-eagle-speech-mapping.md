# Eagle 语音识别映射 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Eagle 标签可按人声质量筛选，并在素材描述中直接展示带原视频时间范围的语音识别结果。

**Architecture:** 默认映射把 `speech_quality` 作为普通低基数标签。`AssetMapper` 接收项目目录，通过专用函数读取并校验 `TranscriptDocument`，再生成“语音识别”描述章节；读取失败只生成局部降级文本。CLI 负责把当前项目目录传给 mapper，Eagle runner 和客户端协议保持不变。

**Tech Stack:** Python 3.11、Pydantic v2、PyYAML、pytest、Eagle V2 Web API。

## Global Constraints

- 质量标签必须严格使用 `tc:speech_quality:<none|unclear|clear>`。
- 转写文本不得写入 Eagle 标签。
- 描述时间范围必须使用原视频时间轴，文本保持原语言。
- 单个转写缺失、不可读或非法不得中断其他素材同步。
- `speech_quality=null` 时不生成质量标签或“语音识别”章节。

---

### Task 1: Eagle 人声映射与描述渲染

**Files:**
- Modify: `tests/test_eagle_asset_mapper.py`
- Modify: `src/tripclipper/eagle_sync.py`
- Modify: `src/tripclipper/templates/eagle_mapping.default.yaml`
- Modify: `src/tripclipper/cli.py`
- Modify: `openspec/changes/audio-speech-analysis/tasks.md`

**Interfaces:**
- Consumes: `Asset.speech_quality`, `Asset.transcript_path`, `TranscriptDocument.model_validate_json()`。
- Produces: `AssetMapper(..., project_dir: Path | None = None)`；`AssetWritePlan.tags` 中的质量标签；`AssetWritePlan.annotation` 中的“语音识别”章节。

- [x] **Step 1: 写入失败测试**

在 `tests/test_eagle_asset_mapper.py` 增加临时项目目录和有效转写 JSON，断言 clear 素材生成质量标签、时间范围和原文，但原文不成为标签；另测 none、null 和损坏转写。

```python
def test_plan_maps_clear_speech_to_tag_and_annotation(tmp_path: Path) -> None:
    transcript = tmp_path / "cache/transcripts/asset_x.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        '{"speech_quality":"clear","speech_segments":['
        '{"start_sec":3.5,"end_sec":8.2,"text":"你好 Eagle"}]}',
        encoding="utf-8",
    )
    asset = Asset(
        speech_quality=SpeechQuality.clear,
        transcript_path="cache/transcripts/asset_x.json",
        analysis_status=AnalysisStatus.analyzed,
    )
    plan = AssetMapper(load_mapping_config(), SLUG, TS, tmp_path).plan(asset)
    assert "tc:speech_quality:clear" in plan.tags
    assert "## 语音识别" in plan.annotation
    assert "`00:00:03.5 → 00:00:08.2` 你好 Eagle" in plan.annotation
    assert all("你好 Eagle" not in tag for tag in plan.tags)
```

- [x] **Step 2: 运行测试并确认 RED**

Run: `PYTHONPATH=src .venv/bin/pytest -q tests/test_eagle_asset_mapper.py`

Expected: FAIL，因为 `AssetMapper` 尚不接受项目目录，默认映射也尚未输出 `speech_quality` 标签和描述章节。

- [x] **Step 3: 最小实现映射和 renderer**

在默认 YAML 中增加：

```yaml
speech_quality: { target: tag }
```

在 `eagle_sync.py` 中引入 `TranscriptDocument`，让 mapper 保存可选项目目录，并生成语音章节：

```python
def _render_speech_section(asset: Any, project_dir: Optional[Path]) -> str:
    quality = _get(asset, "speech_quality")
    if quality is None:
        return ""
    if _scalar_str(quality) == "none":
        return "未检测到人声"
    transcript_path = _get(asset, "transcript_path")
    if not transcript_path or project_dir is None:
        return "转写文件不可用"
    path = Path(transcript_path)
    if not path.is_absolute():
        path = project_dir / path
    try:
        document = TranscriptDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return "转写文件不可用"
    if not document.speech_segments:
        return "转写文件不可用"
    return "\n".join(
        f"- `{_format_seconds(s.start_sec)} → {_format_seconds(s.end_sec)}` "
        f"{s.text or '（无法辨认）'}"
        for s in document.speech_segments
    )
```

在 `AssetMapper.plan()` 的 annotation 排序前追加 order 5 的“语音识别”章节；CLI 构造 mapper 时传入 `cut_index_path(project_slug).parent`。

- [x] **Step 4: 运行测试并确认 GREEN**

Run: `PYTHONPATH=src .venv/bin/pytest -q tests/test_eagle_asset_mapper.py tests/test_eagle_sync_runner.py tests/test_eagle_sync_demo_scan.py`

Expected: 全部 PASS。

- [x] **Step 5: 跑回归和规格校验**

Run: `PYTHONPATH=src .venv/bin/pytest -q tests/test_audio_export.py tests/test_exporter.py tests/test_cli_export.py tests/test_eagle_asset_mapper.py tests/test_eagle_sync_runner.py tests/test_eagle_sync_demo_scan.py`

Run: `PATH=/opt/homebrew/bin:$PATH openspec validate audio-speech-analysis --strict`

Expected: 全部 PASS，OpenSpec valid。

- [x] **Step 6: 完成真实 demo-scan 验收**

Run: `PYTHONPATH=src PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m tripclipper.cli run demo-scan --concurrency 1`

Run: `PYTHONPATH=src PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m tripclipper.cli sync-eagle demo-scan --apply`

Expected: 9/9 分析成功且 9/9 同步成功；Eagle Item 的标签包含 `tc:speech_quality:*`，描述包含“语音识别”章节。

- [x] **Step 7: 标记 OpenSpec 任务完成**

把 `tasks.md` 中 7.4 和 7.5 改为 `[x]`；8.2 和 8.3 只有在其完整覆盖条件满足时才能勾选。
