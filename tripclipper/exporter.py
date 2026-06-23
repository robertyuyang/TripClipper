from __future__ import annotations

import csv
import html
from collections import Counter
from pathlib import Path
from typing import Any

from .constants import (
    EDIT_CANDIDATE_LABELS,
    PEOPLE_PRESENCE_LABELS,
    SHOT_FUNCTION_LABELS,
    SHOT_SCALE_LABELS,
    SIMILAR_SELECTION_LABELS,
    SUBJECT_TYPE_LABELS,
)
from .index import append_task_log, load_index, project_dir_from_slug, save_index


ASSET_COLUMNS = [
    "asset_id",
    "file",
    "path",
    "type",
    "duration",
    "rating",
    "scene",
    "subject_type",
    "primary_subject",
    "people_presence",
    "shot_scale",
    "shot_function",
    "tags",
    "summary",
    "similar_group_id",
    "similar_selection",
    "similar_rank",
    "similar_reason",
    "edit_candidate_status",
    "edit_candidate_priority",
    "edit_candidate_reason",
    "audio_suggestion",
    "transcription_status",
    "transcript_path",
    "analysis_status",
    "eagle_item_id",
    "eagle_sync_status",
]

SEGMENT_COLUMNS = [
    "asset_id",
    "file",
    "path",
    "in",
    "out",
    "role",
    "subject_type",
    "shot_scale",
    "rating",
    "reason",
    "audio_strategy",
    "tags",
]


def export_project(project_slug: str, base_dir: str | Path | None = None) -> dict[str, str]:
    project_dir = project_dir_from_slug(project_slug, base_dir)
    data = load_index(project_dir)
    paths = {
        "assets_csv": str(project_dir / "assets.csv"),
        "segments_csv": str(project_dir / "segments.csv"),
        "summary_md": str(project_dir / "summary.md"),
        "review_html": str(project_dir / "review.html"),
        "cut_index": str(project_dir / "cut_index.json"),
    }
    write_assets_csv(project_dir / "assets.csv", data.get("assets", []))
    write_segments_csv(project_dir / "segments.csv", data.get("assets", []))
    (project_dir / "summary.md").write_text(render_summary_markdown(data), encoding="utf-8")
    (project_dir / "review.html").write_text(render_review_html(data), encoding="utf-8")
    append_task_log(data, "export", "导出完成：assets.csv、segments.csv、summary.md、review.html。")
    save_index(project_dir, data)
    return paths


def write_assets_csv(path: Path, assets: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=ASSET_COLUMNS)
        writer.writeheader()
        for asset in assets:
            metadata = asset.get("metadata") or {}
            row = {column: "" for column in ASSET_COLUMNS}
            row.update(
                {
                    "asset_id": asset.get("asset_id"),
                    "file": asset.get("file"),
                    "path": asset.get("path"),
                    "type": asset.get("type"),
                    "duration": metadata.get("duration"),
                    "rating": asset.get("rating"),
                    "scene": asset.get("scene"),
                    "subject_type": asset.get("subject_type"),
                    "primary_subject": asset.get("primary_subject"),
                    "people_presence": asset.get("people_presence"),
                    "shot_scale": asset.get("shot_scale"),
                    "shot_function": asset.get("shot_function"),
                    "tags": ";".join(asset.get("tags") or []),
                    "summary": asset.get("summary"),
                    "similar_group_id": asset.get("similar_group_id"),
                    "similar_selection": asset.get("similar_selection"),
                    "similar_rank": asset.get("similar_rank"),
                    "similar_reason": asset.get("similar_reason"),
                    "edit_candidate_status": asset.get("edit_candidate_status"),
                    "edit_candidate_priority": asset.get("edit_candidate_priority"),
                    "edit_candidate_reason": asset.get("edit_candidate_reason"),
                    "audio_suggestion": asset.get("audio_suggestion"),
                    "transcription_status": asset.get("transcription_status"),
                    "transcript_path": asset.get("transcript_path"),
                    "analysis_status": asset.get("analysis_status"),
                    "eagle_item_id": asset.get("eagle_item_id"),
                    "eagle_sync_status": asset.get("eagle_sync_status"),
                }
            )
            writer.writerow(row)


def write_segments_csv(path: Path, assets: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=SEGMENT_COLUMNS)
        writer.writeheader()
        for asset in assets:
            for segment in asset.get("segments") or []:
                writer.writerow(
                    {
                        "asset_id": asset.get("asset_id"),
                        "file": asset.get("file"),
                        "path": asset.get("path"),
                        "in": segment.get("in"),
                        "out": segment.get("out"),
                        "role": segment.get("role"),
                        "subject_type": segment.get("subject_type"),
                        "shot_scale": segment.get("shot_scale"),
                        "rating": segment.get("rating"),
                        "reason": segment.get("reason"),
                        "audio_strategy": segment.get("audio_strategy"),
                        "tags": ";".join(segment.get("tags") or []),
                    }
                )


def render_summary_markdown(data: dict[str, Any]) -> str:
    project = data.get("project") or {}
    assets = data.get("assets") or []
    analyzed = [asset for asset in assets if asset.get("analysis_status") == "analyzed"]
    defaults = [
        asset
        for asset in sorted(analyzed, key=lambda item: item.get("edit_candidate_priority") or 9999)
        if asset.get("edit_candidate_status") == "default_selected"
    ]
    high = [asset for asset in analyzed if (asset.get("rating") or 0) >= 4]
    subject_counts = Counter(asset.get("subject_type") or "unknown" for asset in analyzed)
    scale_counts = Counter(asset.get("shot_scale") or "unknown" for asset in analyzed)

    lines = [
        f"# {project.get('project_name', 'TripClipper 项目')} 总结",
        "",
        "## 项目概览",
        "",
        f"- 素材总数：{len(assets)}",
        f"- 已完成分析：{len(analyzed)}",
        f"- 默认剪辑候选：{len(defaults)}",
        f"- 失败记录：{len(data.get('failures') or [])}",
        f"- 警告记录：{len(data.get('warnings') or [])}",
        "",
        "## 推荐粗剪结构",
        "",
        *_rough_cut_lines(defaults),
        "",
        "## 景别和主体覆盖",
        "",
        *_counter_lines("主体类型", subject_counts, SUBJECT_TYPE_LABELS),
        *_counter_lines("景别", scale_counts, SHOT_SCALE_LABELS),
        "",
        "## 去重后的默认剪辑候选清单",
        "",
        *_asset_lines(defaults),
        "",
        "## 高分素材",
        "",
        *_asset_lines(sorted(high, key=lambda item: (-(item.get("rating") or 0), item.get("file") or ""))[:30]),
        "",
        "## 雷同素材主选建议",
        "",
        *_similar_group_lines(data.get("similar_groups") or [], assets),
        "",
        "## 可用同期声或原声候选",
        "",
        *_audio_lines(analyzed),
        "",
        "## 失败和警告摘要",
        "",
        *_failure_warning_lines(data),
        "",
    ]
    return "\n".join(lines)


def render_review_html(data: dict[str, Any]) -> str:
    project = data.get("project") or {}
    assets = sorted(
        data.get("assets") or [],
        key=lambda item: (
            item.get("edit_candidate_status") != "default_selected",
            item.get("edit_candidate_priority") or 9999,
            item.get("file") or "",
        ),
    )
    rows = "\n".join(_asset_card(asset) for asset in assets)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(project.get('project_name', 'TripClipper'))} Review</title>
  <style>
    :root {{ color-scheme: light; --ink:#17202a; --muted:#5f6b7a; --line:#d8dee8; --bg:#f8fafc; --accent:#0f766e; }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--ink); }}
    header {{ padding:24px 32px 12px; border-bottom:1px solid var(--line); background:#fff; position:sticky; top:0; z-index:2; }}
    h1 {{ font-size:24px; margin:0 0 8px; letter-spacing:0; }}
    .meta {{ color:var(--muted); font-size:14px; display:flex; gap:18px; flex-wrap:wrap; }}
    main {{ padding:24px 32px 48px; max-width:1280px; margin:0 auto; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:16px; }}
    article {{ background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    .thumb {{ height:180px; background:#edf2f7; display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:13px; }}
    .thumb img {{ max-width:100%; max-height:100%; object-fit:contain; }}
    .body {{ padding:14px; }}
    .topline {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }}
    h2 {{ font-size:16px; margin:0; overflow-wrap:anywhere; letter-spacing:0; }}
    .rating {{ font-weight:700; color:var(--accent); white-space:nowrap; }}
    .path {{ color:var(--muted); font-size:12px; overflow-wrap:anywhere; margin:6px 0 12px; }}
    .chips {{ display:flex; flex-wrap:wrap; gap:6px; margin:8px 0; }}
    .chip {{ border:1px solid var(--line); border-radius:999px; padding:3px 8px; font-size:12px; color:#263442; background:#fbfdff; }}
    .status {{ border-color:#99d1c9; color:#075e54; background:#eefbf8; }}
    p {{ font-size:14px; line-height:1.55; margin:8px 0; }}
    table {{ width:100%; border-collapse:collapse; margin-top:8px; font-size:12px; }}
    td {{ border-top:1px solid var(--line); padding:6px 4px; vertical-align:top; }}
    a {{ color:#0f5fbd; }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(project.get('project_name', 'TripClipper'))}</h1>
    <div class="meta">
      <span>素材：{len(assets)}</span>
      <span>默认候选：{len([a for a in assets if a.get('edit_candidate_status') == 'default_selected'])}</span>
      <span>失败：{len(data.get('failures') or [])}</span>
      <span>源目录：{html.escape(project.get('source_folder', ''))}</span>
    </div>
  </header>
  <main>
    <section class="grid">{rows}</section>
  </main>
</body>
</html>
"""


def _asset_card(asset: dict[str, Any]) -> str:
    thumb = _thumbnail_html(asset)
    chips = [
        EDIT_CANDIDATE_LABELS.get(asset.get("edit_candidate_status"), asset.get("edit_candidate_status") or "未入候选"),
        SUBJECT_TYPE_LABELS.get(asset.get("subject_type"), asset.get("subject_type") or "未分析"),
        PEOPLE_PRESENCE_LABELS.get(asset.get("people_presence"), asset.get("people_presence") or ""),
        SHOT_SCALE_LABELS.get(asset.get("shot_scale"), asset.get("shot_scale") or ""),
        SHOT_FUNCTION_LABELS.get(asset.get("shot_function"), asset.get("shot_function") or ""),
        SIMILAR_SELECTION_LABELS.get(asset.get("similar_selection"), asset.get("similar_selection") or ""),
    ]
    chip_html = "".join(
        f'<span class="chip {"status" if chip in {"默认候选", "雷同组主选"} else ""}">{html.escape(str(chip))}</span>'
        for chip in chips
        if chip
    )
    tag_html = "".join(f'<span class="chip">{html.escape(str(tag))}</span>' for tag in asset.get("tags") or [])
    segments = "".join(
        "<tr>"
        f"<td>{html.escape(str(segment.get('in', '')))}-{html.escape(str(segment.get('out', '')))}</td>"
        f"<td>{html.escape(str(segment.get('role', '')))}</td>"
        f"<td>{html.escape(str(segment.get('reason', '')))}</td>"
        "</tr>"
        for segment in asset.get("segments") or []
    )
    media_link = _media_link(asset)
    return f"""<article>
  {thumb}
  <div class="body">
    <div class="topline"><h2>{media_link}</h2><div class="rating">{"★" * int(asset.get('rating') or 0)}</div></div>
    <div class="path">{html.escape(asset.get('path') or '')}</div>
    <div class="chips">{chip_html}</div>
    <p>{html.escape(asset.get('summary') or f"分析状态：{asset.get('analysis_status', 'unknown')}")}</p>
    <p><strong>雷同组：</strong>{html.escape(asset.get('similar_group_id') or '无')} {html.escape(asset.get('similar_reason') or '')}</p>
    <p><strong>声音：</strong>{html.escape(asset.get('audio_suggestion') or '')}</p>
    {_transcript_link_html(asset)}
    <div class="chips">{tag_html}</div>
    <table><tbody>{segments or '<tr><td>暂无推荐片段</td><td></td><td></td></tr>'}</tbody></table>
  </div>
</article>"""


def _thumbnail_html(asset: dict[str, Any]) -> str:
    path = asset.get("thumbnail_path")
    if path and Path(path).exists() and asset.get("type") != "audio":
        return f'<div class="thumb"><img src="{html.escape(Path(path).resolve().as_uri())}" alt=""></div>'
    return f'<div class="thumb">{html.escape(asset.get("type") or "media")}</div>'


def _media_link(asset: dict[str, Any]) -> str:
    path = asset.get("path")
    label = html.escape(asset.get("file") or "")
    if path and Path(path).exists():
        return f'<a href="{html.escape(Path(path).resolve().as_uri())}">{label}</a>'
    return label


def _transcript_link_html(asset: dict[str, Any]) -> str:
    path = asset.get("transcript_path")
    status = asset.get("transcription_status") or "not_started"
    if path and Path(path).exists():
        link = f'<a href="{html.escape(Path(path).resolve().as_uri())}">打开转写文本</a>'
        return f'<p><strong>转写：</strong>{html.escape(status)} · {link}</p>'
    if status in {"failed", "transcribed"}:
        return f"<p><strong>转写：</strong>{html.escape(status)}</p>"
    return ""


def _rough_cut_lines(defaults: list[dict[str, Any]]) -> list[str]:
    if not defaults:
        return ["- 暂无默认候选；请先完成样本或全量分析。"]
    roles = Counter(asset.get("shot_function") or "other" for asset in defaults)
    return [f"- {SHOT_FUNCTION_LABELS.get(role, role)}：{count} 条候选" for role, count in roles.most_common()]


def _counter_lines(title: str, counts: Counter[str], labels: dict[str, str]) -> list[str]:
    if not counts:
        return [f"- {title}：暂无已分析素材。"]
    return [f"- {title} {labels.get(key, key)}：{value}" for key, value in counts.most_common()]


def _asset_lines(assets: list[dict[str, Any]]) -> list[str]:
    if not assets:
        return ["- 暂无。"]
    return [
        (
            f"- {asset.get('file')}：{SUBJECT_TYPE_LABELS.get(asset.get('subject_type'), asset.get('subject_type'))}，"
            f"{SHOT_SCALE_LABELS.get(asset.get('shot_scale'), asset.get('shot_scale'))}，"
            f"{SHOT_FUNCTION_LABELS.get(asset.get('shot_function'), asset.get('shot_function'))}，"
            f"{asset.get('edit_candidate_reason') or asset.get('summary') or ''}"
        )
        for asset in assets
    ]


def _similar_group_lines(groups: list[dict[str, Any]], assets: list[dict[str, Any]]) -> list[str]:
    if not groups:
        return ["- 暂无已识别雷同素材组。"]
    assets_by_id = {asset.get("asset_id"): asset for asset in assets}
    lines: list[str] = []
    for group in groups:
        primary = assets_by_id.get(group.get("primary_asset_id"), {})
        alternates = [assets_by_id.get(asset_id, {}).get("file") for asset_id in group.get("alternate_asset_ids") or []]
        rejected = [assets_by_id.get(asset_id, {}).get("file") for asset_id in group.get("rejected_asset_ids") or []]
        lines.append(
            f"- {group.get('similar_group_id')}：主选 {primary.get('file')}；备选 {', '.join(filter(None, alternates)) or '无'}；"
            f"不推荐 {', '.join(filter(None, rejected)) or '无'}。{group.get('reason') or ''}"
        )
    return lines


def _audio_lines(assets: list[dict[str, Any]]) -> list[str]:
    usable = [
        asset
        for asset in assets
        if "keep" in str(asset.get("audio_strategy") or "") or "保留" in str(asset.get("audio_suggestion") or "")
    ]
    return _asset_lines(usable[:20])


def _failure_warning_lines(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for failure in data.get("failures") or []:
        lines.append(f"- 失败 [{failure.get('stage')}] {failure.get('reason')} 建议：{failure.get('suggestion')}")
    for warning in data.get("warnings") or []:
        lines.append(f"- 警告 [{warning.get('stage')}] {warning.get('reason')} 建议：{warning.get('suggestion')}")
    return lines or ["- 暂无失败或警告。"]
