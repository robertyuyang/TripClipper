from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .analyzer import analyze_project
from .config import create_project_config, load_project_config, validate_model_config
from .constants import (
    EDIT_CANDIDATE_LABELS,
    PEOPLE_PRESENCE_LABELS,
    SHOT_FUNCTION_LABELS,
    SHOT_SCALE_LABELS,
    SIMILAR_SELECTION_LABELS,
    SUBJECT_TYPE_LABELS,
)
from .eagle import eagle_apply, eagle_dry_run
from .exporter import export_project
from .index import load_index, project_dir_from_slug
from .model_config import model_config_status


TASK_LOG: list[dict[str, Any]] = []


def create_app():
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only when optional dependency missing.
        raise RuntimeError("缺少 FastAPI。请先安装项目依赖：pip install -e .") from exc

    app = FastAPI(title="TripClipper", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return _home_html()

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return {"model_config": model_config_status(), "projects": _project_statuses(), "task_log": TASK_LOG[-50:]}

    @app.get("/projects/{project_slug}", response_class=HTMLResponse)
    def project_results(project_slug: str) -> str:
        return _project_results_html(project_slug)

    @app.get("/media/{project_slug}/thumbnail/{asset_id}")
    def project_thumbnail(project_slug: str, asset_id: str):
        path = _thumbnail_path_for_asset(project_slug, asset_id)
        if path is None:
            return JSONResponse({"ok": False, "error": "thumbnail not found"}, status_code=404)
        return FileResponse(path)

    @app.post("/create-config")
    async def create_config(request: Request):
        payload = await request.json()
        try:
            config_path = create_project_config(payload)
            _log("create_config", f"已创建配置：{config_path}")
            return {"ok": True, "config_path": str(config_path)}
        except Exception as exc:
            _log("create_config", str(exc), "error")
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @app.post("/scan")
    async def scan(request: Request):
        payload = await request.json()
        return _run_json("scan", lambda: analyze_project(payload["config_path"], "scan"))

    @app.post("/analyze")
    async def analyze(request: Request):
        payload = await request.json()
        stage = payload.get("stage") or "sample"
        force = bool(payload.get("force"))
        return _run_json(stage, lambda: analyze_project(payload["config_path"], stage, force=force))

    @app.post("/export")
    async def export(request: Request):
        payload = await request.json()
        return _run_json("export", lambda: export_project(payload["project"]))

    @app.post("/sync-eagle")
    async def sync_eagle(request: Request):
        payload = await request.json()
        mode = payload.get("mode") or "dry-run"
        if mode == "apply":
            return _run_json("eagle_apply", lambda: eagle_apply(payload["project"]))
        return _run_json("eagle_dry_run", lambda: eagle_dry_run(payload["project"]))

    return app


def _run_json(stage: str, callback):
    _log(stage, "开始执行。")
    try:
        result = callback()
        _log(stage, "完成。")
        return {"ok": True, "result": result}
    except Exception as exc:
        _log(stage, str(exc), "error")
        return {"ok": False, "error": str(exc)}


def _project_statuses() -> list[dict[str, Any]]:
    root = Path.cwd() / "projects"
    statuses: list[dict[str, Any]] = []
    if not root.exists():
        return statuses
    for project_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        try:
            data = load_index(project_dir)
        except Exception:
            data = _project_stub(project_dir)
        assets = data.get("assets") or []
        model_errors = _model_errors(data, project_dir)
        statuses.append(
            {
                "project_slug": (data.get("project") or {}).get("project_slug", project_dir.name),
                "project_name": (data.get("project") or {}).get("project_name", project_dir.name),
                "config_path": str(project_dir / "project.yaml"),
                "asset_count": len(assets),
                "analyzed_count": len([asset for asset in assets if asset.get("analysis_status") == "analyzed"]),
                "transcribed_count": len([asset for asset in assets if asset.get("transcription_status") == "transcribed"]),
                "failed_count": len(data.get("failures") or []),
                "warning_count": len(data.get("warnings") or []),
                "analysis_status": (data.get("analysis") or {}).get("status", "not_started"),
                "model_ready": not model_errors,
                "model_errors": model_errors,
                "next_step": _next_step(data),
            }
        )
    return statuses


def _next_step(data: dict[str, Any]) -> str:
    assets = data.get("assets") or []
    if not assets:
        return "执行扫描"
    if not any(asset.get("analysis_status") == "analyzed" for asset in assets):
        return "执行样本分析"
    if any(asset.get("analysis_status") not in {"analyzed", "analysis_failed"} for asset in assets):
        return "执行全量分析"
    return "导出数据包或预览 Eagle 同步"


def _log(stage: str, message: str, level: str = "info") -> None:
    TASK_LOG.append({"stage": stage, "level": level, "message": message})
    del TASK_LOG[:-100]


def _project_stub(project_dir: Path) -> dict[str, Any]:
    config_path = project_dir / "project.yaml"
    if not config_path.exists():
        return {"project": {"project_slug": project_dir.name, "project_name": project_dir.name}, "assets": []}
    try:
        config = load_project_config(config_path)
        return {
            "project": {
                "project_slug": config.project_slug,
                "project_name": config.project_name,
                "source_folder": str(config.source_folder),
                "config_path": str(config_path),
                "model_config_summary": config.model_config_summary,
            },
            "analysis": {"status": "not_started"},
            "assets": [],
            "failures": [],
            "warnings": [],
        }
    except Exception:
        return {"project": {"project_slug": project_dir.name, "project_name": project_dir.name}, "assets": []}


def _model_errors(data: dict[str, Any], project_dir: Path) -> list[str]:
    config_path = project_dir / "project.yaml"
    if config_path.exists():
        try:
            model_config = load_project_config(config_path).model_config_summary
            return validate_model_config(model_config)
        except Exception:
            pass

    model_config = ((data.get("project") or {}).get("model_config_summary") or {}).copy()
    return validate_model_config(model_config)


def _project_results_html(project_slug: str, base_dir: str | Path | None = None) -> str:
    project_dir = project_dir_from_slug(project_slug, base_dir)
    try:
        data = load_index(project_dir)
    except Exception:
        data = _project_stub(project_dir)
    project = data.get("project") or {}
    assets = sorted(data.get("assets") or [], key=lambda item: item.get("relative_path") or item.get("file") or "")
    analyzed_count = len([asset for asset in assets if asset.get("analysis_status") == "analyzed"])
    transcribed_count = len([asset for asset in assets if asset.get("transcription_status") == "transcribed"])
    failed_count = len([asset for asset in assets if asset.get("analysis_status") == "analysis_failed"])
    selected_count = len([asset for asset in assets if asset.get("edit_candidate_status") == "default_selected"])
    rows = "\n".join(_result_table_row(project_slug, asset) for asset in assets)
    if not rows:
        rows = '<tr><td colspan="8" class="empty">这个项目还没有扫描到素材。</td></tr>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(project.get('project_name') or project_slug)} · 分析结果</title>
  <style>
    :root {{ color-scheme: light; --ink:#17202a; --muted:#5f6b7a; --line:#d8dee8; --bg:#f6f8fb; --panel:#fff; --accent:#0f766e; --soft:#eef7f6; --warn:#9a3412; --bad:#b42318; --ok:#047857; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--ink); }}
    header {{ position:sticky; top:0; z-index:3; background:var(--panel); border-bottom:1px solid var(--line); padding:18px 24px 14px; }}
    .topbar {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }}
    h1 {{ margin:0 0 6px; font-size:22px; letter-spacing:0; }}
    .meta {{ color:var(--muted); font-size:13px; display:flex; flex-wrap:wrap; gap:12px; }}
    .actions {{ display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }}
    a.button, button {{ border:1px solid #0d9488; background:#0f766e; color:#fff; border-radius:6px; padding:8px 11px; font-weight:700; cursor:pointer; text-decoration:none; font-size:14px; line-height:1.2; }}
    a.button.secondary, button.secondary {{ background:#fff; color:#0f766e; }}
    main {{ padding:20px 24px 36px; }}
    .table-wrap {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:auto; }}
    table {{ width:100%; min-width:1320px; border-collapse:separate; border-spacing:0; }}
    th {{ background:#f9fbfd; color:#394657; border-bottom:1px solid var(--line); font-size:12px; text-align:left; padding:10px; white-space:nowrap; }}
    td {{ border-bottom:1px solid var(--line); padding:10px; vertical-align:top; font-size:13px; line-height:1.45; }}
    tr:last-child td {{ border-bottom:0; }}
    .thumb {{ width:112px; min-width:112px; }}
    .thumb-box {{ width:96px; height:56px; border:1px solid var(--line); border-radius:6px; background:#edf2f7; display:flex; align-items:center; justify-content:center; color:var(--muted); overflow:hidden; font-size:12px; }}
    .thumb-box img {{ width:100%; height:100%; object-fit:cover; display:block; }}
    .file {{ width:220px; max-width:220px; }}
    .file a {{ color:#0f5fbd; text-decoration:none; font-weight:700; overflow-wrap:anywhere; }}
    .path {{ margin-top:5px; color:var(--muted); font-size:12px; overflow-wrap:anywhere; }}
    .summary {{ width:300px; max-width:300px; }}
    .detail {{ width:210px; max-width:210px; }}
    .segments {{ width:280px; max-width:280px; }}
    .muted {{ color:var(--muted); }}
    .pill-row {{ display:flex; flex-wrap:wrap; gap:5px; margin-top:6px; }}
    .pill {{ border:1px solid var(--line); background:#fbfdff; border-radius:999px; padding:2px 7px; font-size:12px; color:#263442; }}
    .pill.ok {{ border-color:#99d1c9; background:var(--soft); color:#075e54; }}
    .pill.bad {{ border-color:#fecaca; background:#fff1f2; color:var(--bad); }}
    .rating {{ color:#0f766e; font-weight:800; white-space:nowrap; }}
    .status {{ font-weight:800; color:var(--ok); }}
    .status.pending {{ color:var(--muted); }}
    .status.failed {{ color:var(--bad); }}
    .line {{ margin:0 0 4px; }}
    .empty {{ color:var(--muted); padding:28px; text-align:center; }}
    @media (max-width: 780px) {{
      header {{ position:static; padding:16px; }}
      .topbar {{ display:block; }}
      .actions {{ justify-content:flex-start; margin-top:12px; }}
      main {{ padding:14px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div>
        <h1>{_escape(project.get('project_name') or project_slug)}</h1>
        <div class="meta">
          <span>{_escape(project_slug)}</span>
          <span>素材 {len(assets)}</span>
          <span>已分析 {analyzed_count}</span>
          <span>已转写 {transcribed_count}</span>
          <span>分析失败 {failed_count}</span>
          <span>默认候选 {selected_count}</span>
          <span>源目录：{_escape(project.get('source_folder') or '')}</span>
        </div>
      </div>
      <div class="actions">
        <a class="button secondary" href="/">首页</a>
        <button onclick="window.location.reload()">刷新</button>
      </div>
    </div>
  </header>
  <main>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>微缩图</th>
            <th>文件</th>
            <th>状态</th>
            <th>摘要和标签</th>
            <th>主体与镜头</th>
            <th>推荐片段</th>
            <th>声音与候选</th>
            <th>Eagle</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </div>
  </main>
</body>
</html>"""


def _result_table_row(project_slug: str, asset: dict[str, Any]) -> str:
    status = asset.get("analysis_status") or "unknown"
    status_class = "failed" if status == "analysis_failed" else "pending" if status != "analyzed" else ""
    status_label = {
        "analyzed": "已分析",
        "analysis_failed": "分析失败",
        "scanned": "已扫描",
    }.get(status, status)
    metadata = asset.get("metadata") or {}
    type_label = {"video": "视频", "image": "图片", "audio": "音频"}.get(asset.get("type"), asset.get("type") or "素材")
    candidate = EDIT_CANDIDATE_LABELS.get(asset.get("edit_candidate_status"), asset.get("edit_candidate_status") or "未入候选")
    similar = SIMILAR_SELECTION_LABELS.get(asset.get("similar_selection"), asset.get("similar_selection") or "无雷同组")
    candidate_class = "ok" if asset.get("edit_candidate_status") == "default_selected" else ""
    return f"""<tr>
  <td class="thumb">{_thumbnail_cell(project_slug, asset)}</td>
  <td class="file">
    {_asset_link(asset)}
    <div class="path">{_escape(asset.get('relative_path') or asset.get('path') or '')}</div>
    <div class="pill-row">
      <span class="pill">{_escape(type_label)}</span>
      <span class="pill">{_escape(metadata.get('duration') or '无时长')}</span>
    </div>
  </td>
  <td>
    <div class="status {status_class}">{_escape(status_label)}</div>
    <div class="rating">{_rating(asset.get('rating'))}</div>
    <div class="muted">{_escape(asset.get('asset_id') or '')}</div>
  </td>
  <td class="summary">
    <div>{_escape(asset.get('summary') or '暂无分析摘要。')}</div>
    {_tags_html(asset.get('tags') or [])}
  </td>
  <td class="detail">
    <div class="line"><strong>主体：</strong>{_escape(_label(SUBJECT_TYPE_LABELS, asset.get('subject_type')))}</div>
    <div class="line"><strong>主要主体：</strong>{_escape(asset.get('primary_subject') or '未分析')}</div>
    <div class="line"><strong>人物：</strong>{_escape(_label(PEOPLE_PRESENCE_LABELS, asset.get('people_presence')))}</div>
    <div class="line"><strong>景别：</strong>{_escape(_label(SHOT_SCALE_LABELS, asset.get('shot_scale')))}</div>
    <div class="line"><strong>功能：</strong>{_escape(_label(SHOT_FUNCTION_LABELS, asset.get('shot_function')))}</div>
  </td>
  <td class="segments">{_segments_html(asset.get('segments') or [])}</td>
  <td class="detail">
    <div class="line"><strong>声音：</strong>{_escape(asset.get('audio_suggestion') or '无')}</div>
    <div class="line"><strong>转写：</strong>{_transcript_link_html(asset)}</div>
    <div class="pill-row">
      <span class="pill {candidate_class}">{_escape(candidate)}</span>
      <span class="pill">{_escape(similar)}</span>
    </div>
    <div class="muted">{_escape(asset.get('edit_candidate_reason') or asset.get('similar_reason') or '')}</div>
  </td>
  <td>
    <div>{_escape(asset.get('eagle_sync_status') or 'not_synced')}</div>
    <div class="muted">{_escape(asset.get('eagle_item_id') or '')}</div>
  </td>
</tr>"""


def _thumbnail_cell(project_slug: str, asset: dict[str, Any]) -> str:
    if _asset_thumbnail_path(asset) is None:
        return f'<div class="thumb-box">{_escape(asset.get("type") or "media")}</div>'
    src = f"/media/{_escape(project_slug)}/thumbnail/{_escape(asset.get('asset_id') or '')}"
    return f'<div class="thumb-box"><img src="{src}" alt=""></div>'


def _asset_link(asset: dict[str, Any]) -> str:
    label = _escape(asset.get("file") or asset.get("filename") or "")
    path = asset.get("path")
    if path and Path(path).exists():
        return f'<a href="{_escape(Path(path).resolve().as_uri())}">{label}</a>'
    return f"<strong>{label}</strong>"


def _transcript_link_html(asset: dict[str, Any]) -> str:
    path = asset.get("transcript_path")
    status = asset.get("transcription_status") or "not_started"
    if path and Path(path).exists():
        return f'<a href="{_escape(Path(path).resolve().as_uri())}">{_escape(status)}</a>'
    return _escape(status)


def _tags_html(tags: list[Any]) -> str:
    if not tags:
        return '<div class="pill-row"><span class="pill">暂无标签</span></div>'
    return '<div class="pill-row">' + "".join(f'<span class="pill">{_escape(tag)}</span>' for tag in tags) + "</div>"


def _segments_html(segments: list[dict[str, Any]]) -> str:
    if not segments:
        return '<span class="muted">暂无推荐片段</span>'
    lines = []
    for segment in segments[:3]:
        time_range = f"{segment.get('in') or ''}-{segment.get('out') or ''}".strip("-")
        role = _label(SHOT_FUNCTION_LABELS, segment.get("role"))
        reason = segment.get("reason") or ""
        lines.append(
            f'<div class="line"><strong>{_escape(time_range or "片段")}</strong> '
            f'{_escape(role)}：{_escape(reason)}</div>'
        )
    if len(segments) > 3:
        lines.append(f'<div class="muted">还有 {len(segments) - 3} 个片段</div>')
    return "".join(lines)


def _rating(value: Any) -> str:
    try:
        rating = int(value or 0)
    except (TypeError, ValueError):
        rating = 0
    if rating <= 0:
        return "未评分"
    return "★" * max(1, min(rating, 5))


def _label(labels: dict[str, str], value: Any) -> str:
    if not value:
        return "未分析"
    return labels.get(str(value), str(value))


def _escape(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _thumbnail_path_for_asset(
    project_slug: str,
    asset_id: str,
    base_dir: str | Path | None = None,
) -> Path | None:
    project_dir = project_dir_from_slug(project_slug, base_dir)
    data = load_index(project_dir)
    for asset in data.get("assets") or []:
        if asset.get("asset_id") == asset_id:
            return _asset_thumbnail_path(asset)
    return None


def _asset_thumbnail_path(asset: dict[str, Any]) -> Path | None:
    for key in ("thumbnail_path",):
        value = asset.get(key)
        if value and Path(value).exists():
            return Path(value)
    for value in asset.get("frame_paths") or []:
        if value and Path(value).exists():
            return Path(value)
    return None


def _home_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TripClipper</title>
  <style>
    :root { color-scheme: light; --ink:#17202a; --muted:#657181; --line:#d8dee8; --bg:#f6f8fb; --panel:#fff; --accent:#0f766e; --warn:#9a3412; --ok:#047857; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--ink); }
    header { padding:20px 28px; background:var(--panel); border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; gap:16px; }
    h1 { margin:0; font-size:22px; letter-spacing:0; }
    main { padding:24px 28px; max-width:1200px; margin:0 auto; display:grid; grid-template-columns:360px 1fr; gap:20px; }
    section { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }
    h2 { margin:0 0 12px; font-size:16px; letter-spacing:0; }
    label { display:block; font-size:12px; color:var(--muted); margin:12px 0 4px; }
    input, select { width:100%; border:1px solid var(--line); border-radius:6px; padding:9px 10px; font-size:14px; background:#fff; }
    button { border:1px solid #0d9488; background:#0f766e; color:#fff; border-radius:6px; padding:9px 12px; font-weight:600; cursor:pointer; }
    button.secondary { background:#fff; color:#0f766e; }
    a.button-link { border:1px solid #0d9488; background:#fff; color:#0f766e; border-radius:6px; padding:9px 12px; font-weight:600; text-decoration:none; line-height:1.2; display:inline-flex; align-items:center; }
    button:disabled { cursor:wait; opacity:.62; }
    .row { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }
    .project { border-top:1px solid var(--line); padding:12px 0; }
    .project:first-child { border-top:0; padding-top:0; }
    .name { font-weight:700; }
    .meta { color:var(--muted); font-size:13px; margin:4px 0; }
    .notice { border:1px solid #fed7aa; background:#fff7ed; color:var(--warn); padding:10px 12px; border-radius:8px; font-size:13px; line-height:1.45; margin-bottom:12px; }
    .model { font-size:13px; margin:6px 0; }
    .model.ok { color:var(--ok); }
    .model.bad { color:var(--warn); }
    .output-panel { position:sticky; top:12px; z-index:2; background:var(--panel); border-bottom:1px solid var(--line); margin-bottom:12px; padding-bottom:12px; }
    .output-panel h2 { margin-bottom:8px; }
    .output-panel pre { margin:0; max-height:220px; }
    .status-line { display:flex; align-items:center; gap:8px; min-height:20px; margin:0 0 8px; font-size:13px; color:var(--muted); }
    .status-line.busy { color:var(--accent); }
    .status-line.ok { color:var(--ok); }
    .status-line.error { color:var(--warn); }
    .status-line.busy::before { content:""; width:8px; height:8px; border-radius:999px; background:var(--accent); animation:pulse 1s ease-in-out infinite; }
    @keyframes pulse { 0%, 100% { opacity:.35; transform:scale(.82); } 50% { opacity:1; transform:scale(1); } }
    pre { white-space:pre-wrap; background:#101820; color:#e6edf3; padding:12px; border-radius:8px; max-height:260px; overflow:auto; }
    @media (max-width: 860px) { main { grid-template-columns:1fr; padding:16px; } header { padding:16px; } }
  </style>
</head>
<body>
  <header><h1>TripClipper</h1><button class="secondary" onclick="refresh()">刷新状态</button></header>
  <main>
    <section>
      <h2>创建项目</h2>
      <div class="notice">Stage 2 必须调用真实模型。模型配置从本地 .env 或启动进程环境变量读取，不在页面里填写；TripClipper 不会生成假分析。</div>
      <label>项目名称</label><input id="project_name" placeholder="2026 Japan Trip">
      <label>素材目录</label><input id="source_folder" placeholder="/Users/me/Movies/japan-trip">
      <label>成片风格</label><input id="output_style" value="travel_vlog">
      <label>目标时长</label><input id="target_length" value="3min">
      <label>受众</label><input id="audience" value="friends">
      <label>人物优先级</label><select id="people_focus"><option>medium</option><option>high</option><option>low</option></select>
      <label>声音优先级</label><select id="audio_priority"><option>medium</option><option>high</option><option>low</option></select>
      <div class="row"><button onclick="createProject(this)">创建配置</button></div>
    </section>
    <section>
      <div class="output-panel">
        <h2>操作输出</h2>
        <div id="operation_status" class="status-line idle">空闲</div>
        <pre id="output">等待操作...</pre>
      </div>
      <h2>真实模型状态</h2>
      <div id="model_config" class="meta">读取中...</div>
      <div class="notice">配置文件示例：在仓库根目录创建 .env，写入 TRIPCLIPPER_MODEL_BASE_URL、TRIPCLIPPER_VISION_MODEL、TRIPCLIPPER_TEXT_MODEL、TRIPCLIPPER_MODEL_API_KEY。</div>
      <h2>项目状态</h2>
      <div id="projects"></div>
    </section>
  </main>
<script>
const draftFields = ['project_name','source_folder','output_style','target_length','audience','people_focus','audio_priority'];
const htmlEscapes = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;', "'":'&#39;'};
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => htmlEscapes[char]);
}
function payloadAttr(value) {
  return escapeHtml(JSON.stringify(value));
}
function formatTime(date = new Date()) {
  return date.toLocaleTimeString('zh-CN', {hour12:false});
}
function loadDraft() {
  const raw = localStorage.getItem('tripclipper.projectDraft');
  if (!raw) return;
  try {
    const draft = JSON.parse(raw);
    for (const id of draftFields) {
      if (draft[id] !== undefined && document.getElementById(id)) document.getElementById(id).value = draft[id];
    }
  } catch (error) {
    console.warn('Cannot load TripClipper draft', error);
  }
}
function saveDraft() {
  const draft = {};
  for (const id of draftFields) draft[id] = document.getElementById(id).value;
  localStorage.setItem('tripclipper.projectDraft', JSON.stringify(draft));
}
window.addEventListener('DOMContentLoaded', () => {
  loadDraft();
  for (const id of draftFields) document.getElementById(id).addEventListener('input', saveDraft);
});
function setOperationStatus(message, state = 'idle') {
  const node = document.getElementById('operation_status');
  if (!node) return;
  node.className = `status-line ${state}`;
  node.textContent = message;
}
function writeOutput(message, data) {
  const output = document.getElementById('output');
  output.textContent = data === undefined ? message : `${message}\n\n${JSON.stringify(data, null, 2)}`;
  output.scrollTop = 0;
}
function setButtonsBusy(isBusy, activeButton = null, action = '') {
  document.querySelectorAll('button').forEach(button => {
    if (isBusy) {
      button.dataset.originalText = button.dataset.originalText || button.textContent;
      button.disabled = true;
    } else {
      button.disabled = false;
      if (button.dataset.originalText) {
        button.textContent = button.dataset.originalText;
        delete button.dataset.originalText;
      }
    }
  });
  if (isBusy && activeButton) activeButton.textContent = `${action}中...`;
}
async function parseJsonResponse(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch (error) {
    return {ok:false, error:text};
  }
}
async function refreshSafely() {
  try {
    await refresh();
  } catch (error) {
    console.warn('Cannot refresh TripClipper status', error);
  }
}
async function post(url, payload, action = '操作', sourceButton = null) {
  setButtonsBusy(true, sourceButton, action);
  setOperationStatus(`${action}执行中...`, 'busy');
  writeOutput(`[${formatTime()}] ${action}已开始，正在等待本地任务返回。`);
  try {
    const response = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    const data = await parseJsonResponse(response);
    if (!response.ok || data.ok === false) {
      setOperationStatus(`${action}失败`, 'error');
      writeOutput(`[${formatTime()}] ${action}失败。`, data);
      return data;
    }
    setOperationStatus(`${action}完成`, 'ok');
    writeOutput(`[${formatTime()}] ${action}完成。`, data);
    return data;
  } catch (error) {
    const data = {ok:false, error:error.message || String(error)};
    setOperationStatus(`${action}请求失败`, 'error');
    writeOutput(`[${formatTime()}] ${action}请求失败。`, data);
    return data;
  } finally {
    setButtonsBusy(false);
    await refreshSafely();
  }
}
async function createProject(sourceButton = null) {
  const payload = {};
  for (const id of draftFields) payload[id] = document.getElementById(id).value;
  saveDraft();
  await post('/create-config', payload, '创建配置', sourceButton);
}
document.addEventListener('click', async event => {
  const button = event.target.closest('[data-action-button]');
  if (!button) return;
  const payload = JSON.parse(button.dataset.payload || '{}');
  await post(button.dataset.url, payload, button.dataset.action || '操作', button);
});
async function refresh() {
  const data = await (await fetch('/api/status')).json();
  const model = data.model_config || {};
  document.getElementById('model_config').innerHTML = `
    <div class="model ${model.has_api_key && model.base_url && model.vision_model ? 'ok' : 'bad'}">
      ${model.has_api_key && model.base_url && model.vision_model ? '可用' : '不可用'}
      · provider ${escapeHtml(model.provider || '')}
      · ${escapeHtml(model.vision_model || '未配置视觉模型')}
      · 转写 ${escapeHtml(model.transcription_model || '未配置')}
      · ${escapeHtml(model.base_url || '未配置 Base URL')}
      · ${escapeHtml(model.api_key_env || '未配置 key 环境变量')} ${model.has_api_key ? '已设置' : '未设置'}
    </div>`;
  const root = document.getElementById('projects');
  root.innerHTML = data.projects.map(project => {
    const modelMessage = project.model_ready ? '真实模型：可用' : `真实模型：不可用 - ${(project.model_errors || []).join('；')}`;
    return `
    <div class="project">
      <div class="name">${escapeHtml(project.project_name)}</div>
      <div class="meta">${escapeHtml(project.project_slug)} · 素材 ${project.asset_count} · 已分析 ${project.analyzed_count} · 已转写 ${project.transcribed_count} · 失败 ${project.failed_count} · ${escapeHtml(project.next_step)}</div>
      <div class="model ${project.model_ready ? 'ok' : 'bad'}">${escapeHtml(modelMessage)}</div>
      <div class="row">
        <a class="button-link" href="/projects/${encodeURIComponent(project.project_slug)}" target="_blank" rel="noopener">查看结果</a>
        <button data-action-button data-action="扫描" data-url="/scan" data-payload="${payloadAttr({config_path:project.config_path})}">扫描</button>
        <button data-action-button data-action="提取音频文本" data-url="/analyze" data-payload="${payloadAttr({config_path:project.config_path, stage:'transcribe'})}">提取音频文本</button>
        <button data-action-button data-action="样本分析" data-url="/analyze" data-payload="${payloadAttr({config_path:project.config_path, stage:'sample'})}">样本分析</button>
        <button data-action-button data-action="全量分析" data-url="/analyze" data-payload="${payloadAttr({config_path:project.config_path, stage:'full'})}">全量分析</button>
        <button data-action-button data-action="导出" data-url="/export" data-payload="${payloadAttr({project:project.project_slug})}">导出</button>
        <button data-action-button data-action="Eagle 预览" data-url="/sync-eagle" data-payload="${payloadAttr({project:project.project_slug, mode:'dry-run'})}">Eagle 预览</button>
        <button class="secondary" data-action-button data-action="Eagle 同步" data-url="/sync-eagle" data-payload="${payloadAttr({project:project.project_slug, mode:'apply'})}">Eagle 同步</button>
      </div>
    </div>`;
  }).join('') || '<div class="meta">暂无项目</div>';
}
window.addEventListener('DOMContentLoaded', refresh);
</script>
</body>
</html>"""
