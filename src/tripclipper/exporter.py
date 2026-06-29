"""HTML report renderer (M5-early).

Reads a project's ``cut_index.json`` and writes
``projects/<slug>/exports/review.html`` — a single self-contained HTML file
that lets the user visually verify model output (M3) and, after M4 lands,
similar-group / edit-candidate decisions.

Design notes (brainstorming Q1–Q10):
- No template engine: a single template file with three ``__VARNAME__``
  placeholders, replaced via ``str.replace``.
- M4 fields render the literal string ``"（待 M4）"`` for now; only the
  ``_asset_to_row`` branches change when M4 lands. Table structure / CSS / JS
  stay frozen.
- All user text passes through ``html.escape``. The embedded JSON block has
  any literal ``</script>`` sequence escaped before injection to prevent
  script injection.
- ``__JSON_DATA__`` is a deep copy of the cut_index with
  ``project.model_config_summary`` deleted before serialisation, even though
  it never holds key material directly — keeps a single defensive boundary.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Optional

from .cut_index import read_cut_index
from .models import (
    AnalysisStatus,
    Asset,
    CutIndex,
    EditCandidateStatus,
    Segment,
    SimilarGroup,
    SimilarSelection,
)
from .paths import cut_index_path, exports_dir, project_dir, review_html_path

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "review.html.tmpl"

# Truncation limits (kept here, not in spec — easy to adjust)
_SUMMARY_MAX_LEN = 80
_FAILURE_REASON_MAX_LEN = 80
_SIMILAR_REASON_MAX_LEN = 80
_CANDIDATE_REASON_MAX_LEN = 80
_TAGS_VISIBLE = 5
_KIB = 1024
_MIB = _KIB * 1024
_GIB = _MIB * 1024


class ExportError(Exception):
    """Raised when render_review_html fails (project missing, IO error)."""


# ---------------------------------------------------------------------------
# Pure formatters
# ---------------------------------------------------------------------------


def _format_duration(seconds: Optional[float]) -> str:
    """Format duration as ``mm:ss``. ``None`` / ``0`` -> ``""``."""
    if seconds is None:
        return ""
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    minutes, sec = divmod(total, 60)
    return f"{minutes:02d}:{sec:02d}"


def _format_size(size: Optional[int]) -> str:
    """Format byte count as ``X.X MB`` / ``X.X GB``. ``None`` / ``<= 0`` -> ``""``."""
    if size is None:
        return ""
    try:
        n = int(size)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    if n >= _GIB:
        return f"{n / _GIB:.1f} GB"
    if n >= _MIB:
        return f"{n / _MIB:.1f} MB"
    if n >= _KIB:
        return f"{n / _KIB:.1f} KB"
    return f"{n} B"


def _format_modified_time(ts: Optional[str]) -> str:
    """Trim an ISO-8601 timestamp to ``YYYY-MM-DD HH:MM`` for display."""
    if not ts:
        return ""
    s = str(ts).replace("T", " ")
    # strip seconds + timezone if present (keep first 16 chars: "YYYY-MM-DD HH:MM")
    return s[:16]


def _format_media_info(asset: Asset) -> str:
    """Render the type cell as a multi-line media info block.

    Line 1: ``video · 00:12``
    Line 2: ``1920×1080 · hevc · 60fps`` (omits empty parts)
    Line 3: ``22.5 MB · 含音频`` (omits empty parts)
    """
    asset_type = _enum_value(asset.type)
    metadata = asset.metadata or {}

    duration_text = _format_duration(metadata.get("duration"))
    line1_parts = [asset_type] if asset_type else []
    if duration_text:
        line1_parts.append(duration_text)
    line1 = " · ".join(line1_parts)

    width = metadata.get("width")
    height = metadata.get("height")
    line2_parts: list[str] = []
    if width and height:
        line2_parts.append(f"{int(width)}×{int(height)}")
    codec = metadata.get("codec")
    if codec:
        line2_parts.append(str(codec))
    fps = metadata.get("fps")
    if fps:
        try:
            line2_parts.append(f"{int(round(float(fps)))}fps")
        except (TypeError, ValueError):
            pass
    line2 = " · ".join(line2_parts)

    line3_parts: list[str] = []
    size_text = _format_size(asset.size)
    if size_text:
        line3_parts.append(size_text)
    has_audio = metadata.get("has_audio")
    if has_audio is True:
        line3_parts.append("含音频")
    elif has_audio is False:
        line3_parts.append("无音频")
    line3 = " · ".join(line3_parts)

    parts = [line1, line2, line3]
    rendered = "<br>".join(
        f'<span class="media-line">{html.escape(p)}</span>' for p in parts if p
    )
    return rendered or html.escape(asset_type)


def _format_segments(segments: Optional[list[Segment]]) -> str:
    """Render segment list as inline HTML divs. Empty -> ``"（无）"``."""
    if not segments:
        return "（无）"
    parts: list[str] = []
    for seg in segments:
        in_v = html.escape(seg.in_ or "")
        out_v = html.escape(seg.out or "")
        role = html.escape(seg.role or "")
        parts.append(f'<div class="segment">{in_v}-{out_v} {role}</div>')
    return "".join(parts)


def _format_status_class(status: Optional[AnalysisStatus]) -> str:
    if status == AnalysisStatus.analyzed:
        return "status-analyzed"
    if status in (AnalysisStatus.scanned, AnalysisStatus.analyzing):
        return "status-scanned"
    if status == AnalysisStatus.analysis_failed:
        return "status-failed"
    return "status-other"


def _format_row_class(status: Optional[AnalysisStatus]) -> str:
    if status == AnalysisStatus.analysis_failed:
        return "row-failed"
    if status in (AnalysisStatus.scanned, AnalysisStatus.analyzing):
        return "row-pending"
    return ""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _render_summary_cell(asset: Asset) -> str:
    """Render the summary column, with HTML escape applied.

    For ``scanned`` rows where the model hasn't run yet, fall back to the most
    informative scan metadata we have (modified_time / relative_path) so the
    cell isn't blank.
    """
    status = asset.analysis_status
    if status == AnalysisStatus.analysis_failed:
        if asset.failures:
            last = asset.failures[-1]
            reason = ""
            if isinstance(last, dict):
                reason = str(last.get("reason") or "")
            else:
                reason = str(getattr(last, "reason", "") or "")
            if reason:
                return html.escape(_truncate(reason, _FAILURE_REASON_MAX_LEN))
        return "（分析失败）"
    if status == AnalysisStatus.analyzed:
        if asset.summary:
            return html.escape(_truncate(asset.summary, _SUMMARY_MAX_LEN))
        return "（模型未生成 summary）"
    # scanned / analyzing — surface scan-stage info instead of a blank cell
    bits: list[str] = []
    mtime = _format_modified_time(asset.modified_time)
    if mtime:
        bits.append(f"修改时间 {mtime}")
    if asset.relative_path and asset.relative_path != asset.filename:
        bits.append(asset.relative_path)
    if not bits:
        return "（待分析）"
    detail = "<br>".join(html.escape(b) for b in bits)
    return f'<span class="scan-info">（待分析）</span><br>{detail}'


def _format_tags(tags: Optional[list[str]]) -> str:
    if not tags:
        return ""
    visible = tags[:_TAGS_VISIBLE]
    rendered = ", ".join(html.escape(t) for t in visible)
    if len(tags) > _TAGS_VISIBLE:
        rendered += f" (+{len(tags) - _TAGS_VISIBLE})"
    return rendered


def _format_rating(rating: Optional[int]) -> str:
    if rating is None:
        return ""
    try:
        n = int(rating)
    except (TypeError, ValueError):
        return ""
    n = max(0, min(5, n))
    return "★" * n + "☆" * (5 - n)


def _thumbnail_uri(asset: Asset, project_dir_path: Path) -> Optional[str]:
    """Return ``file:///abs/path`` for the thumbnail, or ``None`` if absent.

    ``thumbnail_path`` semantics in :mod:`tripclipper.scan`:

    - Images: an absolute path to the original media file.
    - Videos: a string built from ``thumbnails_dir(slug, base_dir) / f"{stem}.jpg"``,
      i.e. relative to the cwd when ``base_dir`` is ``None`` and absolute when
      tests pass a ``tmp_path``. Either way, resolving relative paths against
      :func:`Path.cwd` matches the writer's contract.
    """
    rel = asset.thumbnail_path
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute():
        p = (Path.cwd() / rel).resolve()
    return "file://" + str(p)


def _thumbnail_uris(asset: Asset) -> list[str]:
    """Return ``file://`` URIs for every browse-aid frame.

    Prefers ``asset.frame_paths`` (the multi-frame strip from scan). Falls back
    to a single-element list with ``thumbnail_path`` when frames are absent.
    Resolves relative paths against cwd, matching scan.py's writer contract.
    """
    raws: list[str] = []
    if asset.frame_paths:
        raws.extend(p for p in asset.frame_paths if p)
    elif asset.thumbnail_path:
        raws.append(asset.thumbnail_path)
    uris: list[str] = []
    seen: set[str] = set()
    for raw in raws:
        p = Path(raw)
        if not p.is_absolute():
            p = (Path.cwd() / raw).resolve()
        uri = "file://" + str(p)
        if uri not in seen:
            seen.add(uri)
            uris.append(uri)
    return uris


def _enum_value(v) -> str:
    """Best-effort string for enum / scalar / None."""
    if v is None:
        return ""
    if hasattr(v, "value"):
        return str(v.value)
    return str(v)


_SIMILAR_SELECTION_CLASS = {
    SimilarSelection.primary: "sel-primary",
    SimilarSelection.alternate: "sel-alternate",
    SimilarSelection.rejected: "sel-rejected",
    SimilarSelection.needs_review: "sel-needs-review",
}

_CANDIDATE_STATUS_CLASS = {
    EditCandidateStatus.default_selected: "cand-default",
    EditCandidateStatus.alternate: "cand-alternate",
    EditCandidateStatus.excluded: "cand-excluded",
    EditCandidateStatus.needs_review: "cand-needs-review",
}


def _format_similar_cell(asset: Asset) -> str:
    """Render the similar_group column for one asset.

    Empty string for assets that aren't part of any similar group.
    """
    sel = asset.similar_selection
    if sel is None or sel == SimilarSelection.none:
        return ""

    sel_value = _enum_value(sel)
    sel_class = _SIMILAR_SELECTION_CLASS.get(sel, "")
    group_id = html.escape(asset.similar_group_id or "")
    rank_text = ""
    if asset.similar_rank is not None:
        rank_text = f" · rank={int(asset.similar_rank)}"

    head_parts = []
    if group_id:
        head_parts.append(group_id)
    head_parts.append(
        f'<span class="{sel_class}">{html.escape(sel_value)}</span>'
        if sel_class
        else html.escape(sel_value)
    )
    head = " · ".join(head_parts) + rank_text

    reason = asset.similar_reason or ""
    if reason:
        truncated = _truncate(reason, _SIMILAR_REASON_MAX_LEN)
        return f'{head}<br><span class="muted">{html.escape(truncated)}</span>'
    return head


def _format_candidate_cell(asset: Asset) -> str:
    """Render the edit_candidate_status column for one asset."""
    status = asset.edit_candidate_status
    if status is None:
        return ""

    status_value = _enum_value(status)
    status_class = _CANDIDATE_STATUS_CLASS.get(status, "")
    head = (
        f'<span class="{status_class}">{html.escape(status_value)}</span>'
        if status_class
        else html.escape(status_value)
    )
    if status == EditCandidateStatus.default_selected and asset.edit_candidate_priority is not None:
        head = f"{head} · priority={int(asset.edit_candidate_priority)}"

    reason = asset.edit_candidate_reason or ""
    if reason:
        truncated = _truncate(reason, _CANDIDATE_REASON_MAX_LEN)
        return f'{head}<br><span class="muted">{html.escape(truncated)}</span>'
    return head


def _render_similar_groups_section(cut: CutIndex) -> str:
    """Render the top-of-page similar-groups panel.

    Returns an empty string when there are no groups, so the template placeholder
    collapses without leaving an empty section container.
    """
    groups = cut.similar_groups or []
    if not groups:
        return ""

    assets_by_id: dict[str, Asset] = {}
    for asset in cut.assets:
        if asset.asset_id:
            assets_by_id[asset.asset_id] = asset

    cards: list[str] = []
    for group in groups:
        cards.append(_render_group_card(group, assets_by_id))

    inner = "\n".join(cards)
    return f'<section class="similar-groups">\n{inner}\n</section>'


def _render_group_card(group: SimilarGroup, assets_by_id: dict[str, Asset]) -> str:
    gid = group.similar_group_id or ""
    header_bits: list[str] = []

    head_text = html.escape(gid) if gid else ""
    if group.confidence is not None:
        try:
            pct = int(round(float(group.confidence) * 100))
            head_text = f"{head_text} · 置信度 {pct}%" if head_text else f"置信度 {pct}%"
        except (TypeError, ValueError):
            pass
    if head_text:
        header_bits.append(f"<span>{head_text}</span>")
    for basis in group.basis or []:
        header_bits.append(f'<span class="basis-chip">{html.escape(basis)}</span>')
    if group.needs_review:
        header_bits.append('<span class="chip-warn">待人工确认</span>')
    header_html = "".join(header_bits)

    members: list[Asset] = []
    for aid in group.asset_ids or []:
        a = assets_by_id.get(aid)
        if a is not None:
            members.append(a)
    members.sort(
        key=lambda a: (
            a.similar_rank is None,
            a.similar_rank if a.similar_rank is not None else 0,
        )
    )

    rows: list[str] = []
    for asset in members:
        rows.append(_render_group_member(asset))
    members_html = "".join(rows)

    return (
        f'<div class="group-card" data-group-id="{html.escape(gid)}">'
        f"<h3>{header_html}</h3>"
        f'<ul class="members">{members_html}</ul>'
        "</div>"
    )


def _render_group_member(asset: Asset) -> str:
    aid = asset.asset_id or ""
    thumb_uris = _thumbnail_uris(asset)
    if thumb_uris:
        thumb_html = (
            f'<img class="group-thumb" src="{html.escape(thumb_uris[0])}" alt="" '
            f'onerror="this.style.display=&quot;none&quot;">'
        )
    else:
        thumb_html = '<div class="no-thumb-mini">×</div>'

    filename = asset.filename or asset.relative_path or asset.path or ""
    tail6 = aid[-6:] if aid else ""
    name_html = (
        f'{html.escape(filename)} '
        f'<span class="muted">{html.escape(tail6)}</span>'
    )

    sel = asset.similar_selection
    if sel is not None and sel != SimilarSelection.none:
        sel_value = _enum_value(sel)
        sel_class = _SIMILAR_SELECTION_CLASS.get(sel, "")
        chip = (
            f'<span class="{sel_class}">{html.escape(sel_value)}</span>'
            if sel_class
            else html.escape(sel_value)
        )
    else:
        chip = ""

    reason_html = ""
    if asset.similar_reason:
        truncated = _truncate(asset.similar_reason, _SIMILAR_REASON_MAX_LEN)
        reason_html = f'<span class="muted">{html.escape(truncated)}</span>'

    stars_html = f'<span class="stars">{_format_rating(asset.rating)}</span>'

    return (
        f'<li data-asset-id="{html.escape(aid)}">'
        f"<div>{thumb_html}</div>"
        f"<div>{name_html}<br>{reason_html}</div>"
        f"<div>{chip}</div>"
        f"<div>{stars_html}</div>"
        "</li>"
    )


def _asset_to_row(asset: Asset, project_dir_path: Path) -> str:
    """Render a single asset as a ``<tr>...</tr>`` HTML string."""
    status = asset.analysis_status
    row_class = _format_row_class(status)
    status_class = _format_status_class(status)

    asset_id = html.escape(asset.asset_id or "")
    subject_type = _enum_value(asset.subject_type)
    shot_scale = _enum_value(asset.shot_scale)
    shot_function = _enum_value(asset.shot_function)
    people_presence = _enum_value(asset.people_presence)
    status_value = _enum_value(status)

    rating_value = "" if asset.rating is None else str(asset.rating)
    filename = asset.filename or asset.relative_path or asset.path or ""
    media_info_html = _format_media_info(asset)

    thumb_uris = _thumbnail_uris(asset)
    if thumb_uris:
        thumb_imgs = "".join(
            f'<img src="{html.escape(uri)}" alt="" '
            f'onerror="this.style.display=&quot;none&quot;">'
            for uri in thumb_uris
        )
        thumb_html = f'<div class="thumb-strip">{thumb_imgs}</div>'
    else:
        thumb_html = '<div class="no-thumb">[无缩略图]</div>'

    tags_html = _format_tags(asset.tags)
    rating_html = f'<span class="stars">{_format_rating(asset.rating)}</span>'
    summary_html = _render_summary_cell(asset)
    segments_html = _format_segments(asset.segments)
    audio_strategy = html.escape(asset.audio_strategy or "")
    primary_subject = html.escape(asset.primary_subject or "")
    subject_cell = html.escape(subject_type)
    if primary_subject:
        subject_cell = (
            f"{subject_cell}<br><span style='color:#888;font-size:11px;'>"
            f"{primary_subject}</span>"
            if subject_cell
            else primary_subject
        )

    search_blob = " ".join(
        [
            (asset.filename or ""),
            (asset.relative_path or ""),
            (asset.summary or ""),
            ", ".join(asset.tags or []),
        ]
    ).strip()

    placeholder_m4_similar = _format_similar_cell(asset)
    placeholder_m4_candidate = _format_candidate_cell(asset)
    status_label = (
        f'<span class="{status_class}">{html.escape(status_value)}</span>'
    )

    similar_gid_attr = html.escape(asset.similar_group_id or "")
    candidate_status_attr = html.escape(_enum_value(asset.edit_candidate_status))

    return (
        f'<tr class="asset-row {row_class}"'
        f' data-asset-id="{asset_id}"'
        f' data-subject-type="{html.escape(subject_type)}"'
        f' data-shot-scale="{html.escape(shot_scale)}"'
        f' data-status="{html.escape(status_value)}"'
        f' data-rating="{html.escape(rating_value)}"'
        f' data-similar-group-id="{similar_gid_attr}"'
        f' data-edit-candidate-status="{candidate_status_attr}"'
        f' data-search="{html.escape(search_blob)}">'
        f'<td class="thumb-cell">{thumb_html}</td>'
        f'<td class="filename-cell" title="{html.escape(filename)}">{html.escape(filename)}</td>'
        f'<td class="media-cell">{media_info_html}</td>'
        f'<td>{rating_html}</td>'
        f'<td>{subject_cell}</td>'
        f'<td>{html.escape(people_presence)}</td>'
        f'<td>{html.escape(shot_scale)}</td>'
        f'<td>{html.escape(shot_function)}</td>'
        f'<td>{tags_html}</td>'
        f'<td class="summary-cell">{summary_html}</td>'
        f'<td>{segments_html}</td>'
        f'<td>{audio_strategy}</td>'
        f'<td>{placeholder_m4_similar}</td>'
        f'<td>{placeholder_m4_candidate}</td>'
        f'<td>{status_label}</td>'
        f'</tr>'
    )


def _render_project_header(cut_index: CutIndex) -> str:
    project = cut_index.project
    model = project.model_config_summary or {}

    counts_by_type: dict[str, int] = {}
    counts_by_status: dict[str, int] = {}
    for asset in cut_index.assets:
        t = _enum_value(asset.type) or "unknown"
        counts_by_type[t] = counts_by_type.get(t, 0) + 1
        s = _enum_value(asset.analysis_status) or "unknown"
        counts_by_status[s] = counts_by_status.get(s, 0) + 1

    type_summary = ", ".join(f"{k}={v}" for k, v in sorted(counts_by_type.items())) or "（无）"
    status_summary = ", ".join(f"{k}={v}" for k, v in sorted(counts_by_status.items())) or "（无）"

    analysis = cut_index.analysis
    analysis_text = "（无）"
    if analysis is not None:
        bits = []
        if analysis.stage:
            bits.append(f"stage={analysis.stage}")
        if analysis.status:
            bits.append(f"status={analysis.status}")
        if analysis.started_at:
            bits.append(f"started_at={analysis.started_at}")
        if analysis.finished_at:
            bits.append(f"finished_at={analysis.finished_at}")
        if bits:
            analysis_text = ", ".join(bits)

    needs_notice = (analysis is None) or (
        getattr(analysis, "status", None) != "completed"
    )

    rows = [
        ("项目名", project.project_name or ""),
        ("slug", project.project_slug or ""),
        ("source_folder", project.source_folder or ""),
        ("provider", str(model.get("provider") or "")),
        ("vision_model", str(model.get("vision_model") or "")),
        ("api_key_env", str(model.get("api_key_env") or "")),
        ("analysis", analysis_text),
        ("素材总数", str(len(cut_index.assets))),
        ("按类型", type_summary),
        ("按 analysis_status", status_summary),
    ]
    dl = "".join(
        f"<dt>{html.escape(k)}</dt><dd>{html.escape(v)}</dd>" for k, v in rows
    )

    notice_html = ""
    if needs_notice:
        notice_html = (
            '<div class="notice">尚未运行 sample/full 分析；表中分析字段可能为空。</div>'
        )

    failures_html = ""
    if cut_index.failures:
        items = []
        for f in cut_index.failures:
            stage = html.escape(getattr(f, "stage", "") or "")
            target = html.escape(getattr(f, "target", "") or "")
            reason = html.escape(getattr(f, "reason", "") or "")
            items.append(f"<div>[{stage}] {target}: {reason}</div>")
        failures_html = (
            '<div class="failures"><b>项目级 failures：</b>' + "".join(items) + "</div>"
        )

    return (
        '<div class="header">'
        f"<dl>{dl}</dl>"
        f"{notice_html}"
        f"{failures_html}"
        "</div>"
    )


def _dump_cut_index_json(cut_index: CutIndex) -> str:
    """Serialise CutIndex to a JSON string with model_config_summary stripped.

    The original ``cut_index`` object is not mutated.
    """
    copy = cut_index.model_copy(deep=True)
    if copy.project is not None:
        copy.project.model_config_summary = {}
    payload = copy.model_dump(mode="json", by_alias=True, exclude_none=False)
    text = json.dumps(payload, ensure_ascii=False)
    return text.replace("</script>", "<\\/script>")


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def render_review_html(
    slug: str,
    *,
    base_dir: Optional[Path] = None,
) -> Path:
    """Render the project's ``cut_index.json`` to ``exports/review.html``.

    Raises :class:`ExportError` if the project is not initialised.
    """
    index_path = cut_index_path(slug, base_dir=base_dir)
    if not index_path.exists():
        raise ExportError(
            f"项目 `{slug}` 尚未初始化，请先运行 `tripclipper init`"
        )
    try:
        cut_index = read_cut_index(index_path)
    except Exception as exc:
        raise ExportError(f"读取 cut_index.json 失败：{exc}") from exc

    pdir = project_dir(slug, base_dir=base_dir)
    rows_html = "\n".join(_asset_to_row(a, pdir) for a in cut_index.assets)
    header_html = _render_project_header(cut_index)
    groups_html = _render_similar_groups_section(cut_index)
    json_data = _dump_cut_index_json(cut_index)

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    rendered = (
        template.replace("__PROJECT_HEADER_HTML__", header_html)
        .replace("__SIMILAR_GROUPS_HTML__", groups_html)
        .replace("__TABLE_ROWS_HTML__", rows_html)
        .replace("__JSON_DATA__", json_data)
    )

    out_dir = exports_dir(slug, base_dir=base_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = review_html_path(slug, base_dir=base_dir)
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


__all__ = [
    "ExportError",
    "render_review_html",
]
