from __future__ import annotations

from pathlib import Path
from typing import Any

from .analyzer import analyze_project
from .config import create_project_config
from .eagle import eagle_apply, eagle_dry_run
from .exporter import export_project
from .index import load_index, project_dir_from_slug


TASK_LOG: list[dict[str, Any]] = []


def create_app():
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import HTMLResponse, JSONResponse
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only when optional dependency missing.
        raise RuntimeError("缺少 FastAPI。请先安装项目依赖：pip install -e .") from exc

    app = FastAPI(title="TripClipper", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return _home_html()

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return {"projects": _project_statuses(), "task_log": TASK_LOG[-50:]}

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
            data = {"project": {"project_slug": project_dir.name, "project_name": project_dir.name}, "assets": []}
        assets = data.get("assets") or []
        statuses.append(
            {
                "project_slug": (data.get("project") or {}).get("project_slug", project_dir.name),
                "project_name": (data.get("project") or {}).get("project_name", project_dir.name),
                "config_path": str(project_dir / "project.yaml"),
                "asset_count": len(assets),
                "analyzed_count": len([asset for asset in assets if asset.get("analysis_status") == "analyzed"]),
                "failed_count": len(data.get("failures") or []),
                "warning_count": len(data.get("warnings") or []),
                "analysis_status": (data.get("analysis") or {}).get("status", "not_started"),
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


def _home_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TripClipper</title>
  <style>
    :root { color-scheme: light; --ink:#17202a; --muted:#657181; --line:#d8dee8; --bg:#f6f8fb; --panel:#fff; --accent:#0f766e; }
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
    .row { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }
    .project { border-top:1px solid var(--line); padding:12px 0; }
    .project:first-child { border-top:0; padding-top:0; }
    .name { font-weight:700; }
    .meta { color:var(--muted); font-size:13px; margin:4px 0; }
    pre { white-space:pre-wrap; background:#101820; color:#e6edf3; padding:12px; border-radius:8px; max-height:260px; overflow:auto; }
    @media (max-width: 860px) { main { grid-template-columns:1fr; padding:16px; } header { padding:16px; } }
  </style>
</head>
<body>
  <header><h1>TripClipper</h1><button class="secondary" onclick="refresh()">刷新状态</button></header>
  <main>
    <section>
      <h2>创建项目</h2>
      <label>项目名称</label><input id="project_name" placeholder="2026 Japan Trip">
      <label>素材目录</label><input id="source_folder" placeholder="/Users/me/Movies/japan-trip">
      <label>成片风格</label><input id="output_style" value="travel_vlog">
      <label>目标时长</label><input id="target_length" value="3min">
      <label>受众</label><input id="audience" value="friends">
      <label>人物优先级</label><select id="people_focus"><option>medium</option><option>high</option><option>low</option></select>
      <label>声音优先级</label><select id="audio_priority"><option>medium</option><option>high</option><option>low</option></select>
      <div class="row"><button onclick="createProject()">创建配置</button></div>
      <h2 style="margin-top:20px">输出</h2>
      <pre id="output">等待操作...</pre>
    </section>
    <section>
      <h2>项目状态</h2>
      <div id="projects"></div>
    </section>
  </main>
<script>
async function post(url, payload) {
  const response = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  const data = await response.json();
  document.getElementById('output').textContent = JSON.stringify(data, null, 2);
  await refresh();
}
async function createProject() {
  const payload = {};
  for (const id of ['project_name','source_folder','output_style','target_length','audience','people_focus','audio_priority']) payload[id] = document.getElementById(id).value;
  payload.model_config = {};
  await post('/create-config', payload);
}
async function refresh() {
  const data = await (await fetch('/api/status')).json();
  const root = document.getElementById('projects');
  root.innerHTML = data.projects.map(project => `
    <div class="project">
      <div class="name">${project.project_name}</div>
      <div class="meta">${project.project_slug} · 素材 ${project.asset_count} · 已分析 ${project.analyzed_count} · 失败 ${project.failed_count} · ${project.next_step}</div>
      <div class="row">
        <button onclick="post('/scan',{config_path:'${project.config_path}'})">扫描</button>
        <button onclick="post('/analyze',{config_path:'${project.config_path}',stage:'sample'})">样本分析</button>
        <button onclick="post('/analyze',{config_path:'${project.config_path}',stage:'full'})">全量分析</button>
        <button onclick="post('/export',{project:'${project.project_slug}'})">导出</button>
        <button onclick="post('/sync-eagle',{project:'${project.project_slug}',mode:'dry-run'})">Eagle 预览</button>
        <button class="secondary" onclick="post('/sync-eagle',{project:'${project.project_slug}',mode:'apply'})">Eagle 同步</button>
      </div>
    </div>`).join('') || '<div class="meta">暂无项目</div>';
}
refresh();
</script>
</body>
</html>"""
