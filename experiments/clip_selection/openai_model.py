"""选片 Agent 专用 OpenAI-compatible JSON 动作客户端。"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx

from tripclipper.config import ModelConfig

from .contracts import AgentDecision


class SelectionModelError(Exception):
    pass


class OpenAISelectionModel:
    def __init__(
        self,
        config: ModelConfig,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        if not config.is_usable():
            raise SelectionModelError("ModelConfig 不可用")
        api_key = os.environ.get(config.api_key_env or "", "")
        if not api_key:
            raise SelectionModelError(f"环境变量 {config.api_key_env} 未设置")
        self.config = config
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=60.0)

    def decide(
        self,
        system_prompt: str,
        context: dict[str, Any],
        images: list[Path] | None = None,
    ) -> AgentDecision:
        user_content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": json.dumps(context, ensure_ascii=False, separators=(",", ":")),
            }
        ]
        for image in images or []:
            mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"
            encoded = base64.b64encode(image.read_bytes()).decode("ascii")
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encoded}"},
                }
            )
        response = self.client.post(
            f"{(self.config.base_url or '').rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.config.vision_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
        )
        try:
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if content.strip().startswith("```"):
                lines = content.strip().splitlines()
                content = "\n".join(lines[1:-1])
            return AgentDecision.model_validate(json.loads(content))
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise SelectionModelError(f"选片模型响应无效: {type(exc).__name__}") from exc

