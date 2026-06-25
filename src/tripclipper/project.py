"""项目创建与初始化编排层（M1 / FR-1）。

把 M0 的"配置加载 + 数据契约 + 目录管理 + 脱敏"组装成用户可触发的
"创建/初始化项目"能力：校验素材目录、生成不含密钥的配置摘要、幂等创建
项目目录并初始化或刷新 ``cut_index.json`` 的 ``project`` 块。

本模块复用 M0 既有 API，不重新定义任何字段、枚举或校验口径。
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict

from .config import ProjectConfig, load_config
from .cut_index import init_cut_index, read_cut_index, write_cut_index
from .models import ProjectInfo, WarningItem
from .paths import (
    cut_index_path,
    ensure_project_dirs,
    project_config_path,
    project_dir,
)
from .security import summarize_model_config

_PathLike = Union[str, Path]

# 模型配置不完整时面向用户的统一文案（摘要 warnings 与 cut_index 警告共用）。
_MODEL_INCOMPLETE_REASON = (
    "模型配置不完整，Stage 2 暂不可执行成功，"
    "请补齐 model_config（provider/base_url/api_key_env/vision_model）"
)
_MODEL_INCOMPLETE_SUGGESTION = (
    "在 project.yaml 的 model_config 中补齐 provider、base_url、"
    "api_key_env、vision_model"
)


class ProjectError(Exception):
    """创建/初始化项目失败时抛出的面向用户的清晰错误。"""


class ProjectSummary(BaseModel):
    """不含密钥的项目配置摘要，供 CLI/API 展示。"""

    # ``model_config_summary``/``model_usable`` 以 ``model_`` 开头会触发 Pydantic v2
    # 保护命名空间告警；这里清空保护命名空间以消除冲突（字段为普通业务字段）。
    model_config = ConfigDict(protected_namespaces=())

    project_name: str
    project_slug: str
    source_folder: str
    source_folder_exists: bool
    editing_intent: dict
    model_config_summary: dict
    model_usable: bool
    project_dir: str
    config_path: str
    cut_index_path: str
    warnings: list[str]


def _utc_now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串。"""
    return datetime.now(timezone.utc).isoformat()


def validate_source_folder(path: _PathLike) -> tuple[bool, Optional[str]]:
    """校验素材目录：存在且为目录返回 ``(True, None)``，否则给出面向用户的原因。"""
    target = Path(path).expanduser()
    if not target.exists():
        return False, (
            f"素材目录不存在：{target}。请确认路径正确，或在 project.yaml 中"
            "将 source_folder 修正为一个已存在的目录。"
        )
    if not target.is_dir():
        return False, (
            f"source_folder 指向的不是目录：{target}。请改为指向一个素材目录。"
        )
    return True, None


def build_project_summary(
    config: ProjectConfig, *, base_dir: Optional[_PathLike] = None
) -> ProjectSummary:
    """由 :class:`ProjectConfig` 生成不含密钥的 :class:`ProjectSummary`。"""
    slug = config.project_slug or ""
    ok, _ = validate_source_folder(config.source_folder)
    model_usable = config.llm.is_usable()

    warnings: list[str] = []
    if not model_usable:
        warnings.append(_MODEL_INCOMPLETE_REASON)

    return ProjectSummary(
        project_name=config.project_name,
        project_slug=slug,
        source_folder=config.source_folder,
        source_folder_exists=ok,
        editing_intent=config.editing_intent.model_dump(),
        model_config_summary=summarize_model_config(config.llm),
        model_usable=model_usable,
        project_dir=str(project_dir(slug, base_dir)),
        config_path=str(project_config_path(slug, base_dir)),
        cut_index_path=str(cut_index_path(slug, base_dir)),
        warnings=warnings,
    )


def scaffold_config_file(
    path: _PathLike,
    *,
    project_name: str,
    source_folder: str,
    force: bool = False,
) -> Path:
    """在 ``path`` 写出一份带建议字段的 ``project.yaml`` 模板。

    模板必填键齐全（project_name/source_folder/model_config），可被
    ``load_config`` 解析；``model_config`` 仅以 ``api_key_env`` 指向环境变量名，
    绝不含密钥明文。``force=False`` 且目标已存在时抛 :class:`ProjectError`。
    """
    target = Path(path).expanduser()
    if target.exists() and not force:
        raise ProjectError(
            f"目标配置文件已存在：{target}。如需覆盖请使用 force=True。"
        )

    template = f"""# TripClipper project.yaml（由 scaffold 生成的模板）
# 安全提示：请勿在本文件中写入密钥明文；api_key_env 指向存放密钥的环境变量名。
project_name: {_yaml_scalar(project_name)}
source_folder: {_yaml_scalar(source_folder)}

# 剪辑意图（聚合为 editing_intent）
output_style:
target_length:
audience:
people_focus:
audio_priority:

model_config:
  provider:
  base_url:
  api_key_env: TRIPCLIPPER_MODEL_API_KEY
  vision_model:
  text_model:
  transcription_model:
  language: zh-CN
  sample_size: 25

eagle_sync:
  enabled: true
  mode: dry-run
  base_url: http://127.0.0.1:41595/api
"""

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template, encoding="utf-8")
    return target


def _yaml_scalar(value: str) -> str:
    """把字符串安全地渲染为单引号 YAML 标量（用于模板填充）。"""
    return "'" + str(value).replace("'", "''") + "'"


def init_project(
    config_path: _PathLike,
    *,
    base_dir: Optional[_PathLike] = None,
    force: bool = False,
) -> ProjectSummary:
    """端到端创建/初始化项目，返回不含密钥的 :class:`ProjectSummary`。

    流程：加载配置 → 校验素材目录 → 幂等建目录 → 逐字复制 project.yaml 到项目
    目录规范位置 → 初始化或刷新 ``cut_index.json`` 的 ``project`` 块 → 返回摘要。
    """
    config = load_config(config_path)  # ConfigError 向上抛，交由调用方处理

    ok, reason = validate_source_folder(config.source_folder)
    if not ok:
        raise ProjectError(reason)

    slug = config.project_slug or ""
    ensure_project_dirs(slug, base_dir)

    # project.yaml 逐字复制到项目目录规范位置（避免重新序列化丢注释/写入密钥）。
    source_yaml = Path(config_path).expanduser().resolve()
    dest_yaml = project_config_path(slug, base_dir)
    dest_resolved = dest_yaml.parent.resolve() / dest_yaml.name
    if source_yaml != dest_resolved:
        shutil.copyfile(source_yaml, dest_yaml)

    # 后续 cut_index.project.config_path 指向项目目录内副本。
    config.config_path = str(dest_yaml)

    index_path = cut_index_path(slug, base_dir)
    now = _utc_now_iso()

    if not index_path.exists():
        cut = init_cut_index(config)
        cut.project.config_path = str(dest_yaml)
    else:
        cut = read_cut_index(index_path)
        created_at = cut.project.created_at or now
        cut.project = ProjectInfo(
            project_name=config.project_name,
            project_slug=config.project_slug,
            source_folder=config.source_folder,
            config_path=str(dest_yaml),
            editing_intent=config.editing_intent.model_dump(),
            model_config_summary=summarize_model_config(config.llm),
            eagle_sync=config.eagle_sync.model_dump(),
            created_at=created_at,
            updated_at=now,
        )

    if not config.llm.is_usable():
        already = any(
            w.stage == "config" and w.reason == _MODEL_INCOMPLETE_REASON
            for w in cut.warnings
        )
        if not already:
            cut.warnings.append(
                WarningItem(
                    stage="config",
                    reason=_MODEL_INCOMPLETE_REASON,
                    suggestion=_MODEL_INCOMPLETE_SUGGESTION,
                    blocking=False,
                )
            )

    write_cut_index(index_path, cut)

    return build_project_summary(config, base_dir=base_dir)


__all__ = [
    "ProjectError",
    "ProjectSummary",
    "validate_source_folder",
    "build_project_summary",
    "scaffold_config_file",
    "init_project",
]
