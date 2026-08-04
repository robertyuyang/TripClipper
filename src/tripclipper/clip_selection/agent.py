"""DeerFlow 选片 Agent 的最小嵌入式入口。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from deerflow.models.openai_codex_provider import CodexChatModel


class MultimodalCodexChatModel(CodexChatModel):
    """保留 Tool 返回的 Responses API 图片内容，而不是压平成文本。"""

    @classmethod
    def _normalize_content(cls, content: Any) -> Any:
        if (
            isinstance(content, list)
            and content
            and all(
                isinstance(item, dict)
                and item.get("type") in {"input_text", "input_image", "input_file"}
                for item in content
            )
        ):
            return content
        return super()._normalize_content(content)


class CodexAuthenticationError(RuntimeError):
    pass


def ensure_codex_authenticated(auth_path: Path | None = None) -> Path:
    """在构造真实模型前确认 Codex 登录文件存在且是有效 JSON。"""
    configured = os.getenv("CODEX_AUTH_PATH")
    path = auth_path or (Path(configured).expanduser() if configured else Path.home() / ".codex" / "auth.json")
    if not path.is_file():
        raise CodexAuthenticationError(
            "未检测到 Codex 登录信息。请先登录 Codex，确保 ~/.codex/auth.json 可用。"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CodexAuthenticationError(
            "Codex 登录信息无法读取。请重新登录 Codex 后再试。"
        ) from exc
    if not isinstance(payload, dict) or not payload:
        raise CodexAuthenticationError(
            "Codex 登录信息为空。请重新登录 Codex 后再试。"
        )
    return path


def build_codex_model() -> Any:
    return MultimodalCodexChatModel(model="gpt-5.4", reasoning_effort="high")


def run_agent(
    *,
    model: Any,
    tools: list[Any],
    system_prompt: str,
    user_prompt: str,
    recursion_limit: int = 200,
) -> dict[str, Any]:
    """用 DeerFlow 的纯参数工厂执行单个连续 Tool Call 循环。"""
    from deerflow.agents.factory import create_deerflow_agent

    graph = create_deerflow_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=[],
        name="tripclipper-clip-selection",
    )
    return graph.invoke(
        {"messages": [("user", user_prompt)]},
        config={"recursion_limit": recursion_limit},
    )


__all__ = [
    "CodexAuthenticationError",
    "MultimodalCodexChatModel",
    "build_codex_model",
    "ensure_codex_authenticated",
    "run_agent",
]
