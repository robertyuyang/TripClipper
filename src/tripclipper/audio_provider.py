"""OpenAI-compatible Gemini audio understanding provider."""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from .audio_analysis import AudioChunk
from .config import ModelConfig

_AUDIO_PROMPT = """分析这段音频中的人类口语，只返回单一 JSON 对象：
{"speech_quality":"none|unclear|clear","speech_segments":[{"start_sec":0.0,"end_sec":1.0,"text":"原文"}]}
只识别人类口语；音乐、歌唱、笑声、哭声和环境声不算口语。
按原语言粗略转写，中英混说保持原样，不翻译，不生成摘要。
确认有人说话但无法辨认时 text 可以为空字符串。时间必须相对于本音频块。
"""

_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


class AudioProviderError(Exception):
    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class AudioAnalysisProvider:
    """Send one WAV chunk per request without exposing sensitive payloads."""

    def __init__(
        self,
        config: ModelConfig,
        *,
        client: Optional[httpx.Client] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not config.is_audio_analysis_usable():
            raise AudioProviderError(
                "ModelConfig 不可用：provider/base_url/api_key_env/vision_model/"
                "audio_analysis_model 必须齐全"
            )
        env_name = config.api_key_env or ""
        api_key = os.environ.get(env_name, "")
        if not api_key:
            raise AudioProviderError(f"环境变量 {env_name} 未设置")
        self._base_url = (config.base_url or "").rstrip("/")
        self._model = config.audio_analysis_model
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=60.0)
        self._sleep = sleep

    def analyze(self, chunk: AudioChunk) -> dict[str, Any]:
        audio_data = base64.b64encode(Path(chunk.path).read_bytes()).decode("ascii")
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _AUDIO_PROMPT},
                        {
                            "type": "input_audio",
                            "input_audio": {"data": audio_data, "format": "wav"},
                        },
                    ],
                }
            ],
            "temperature": 0.1,
            "reasoning_effort": "low",
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"
        attempt = 0
        reasoning_fallback_used = False
        while attempt < 3:
            attempt += 1
            try:
                response = self._client.post(url, headers=headers, json=payload, timeout=60.0)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt < 3:
                    self._sleep(1.0 if attempt == 1 else 4.0)
                    continue
                raise AudioProviderError(
                    f"音频 Provider 网络失败：{type(exc).__name__}", transient=True
                ) from exc

            if response.status_code != 200:
                body_lower = response.text.lower() if response.text else ""
                if (
                    response.status_code == 400
                    and "reasoning_effort" in body_lower
                    and not reasoning_fallback_used
                    and "reasoning_effort" in payload
                ):
                    payload.pop("reasoning_effort", None)
                    reasoning_fallback_used = True
                    attempt -= 1
                    continue
                if response.status_code in _TRANSIENT_STATUS and attempt < 3:
                    self._sleep(1.0 if attempt == 1 else 4.0)
                    continue
                raise AudioProviderError(
                    f"音频 Provider HTTP {response.status_code}",
                    transient=response.status_code in _TRANSIENT_STATUS,
                )

            try:
                envelope = response.json()
                content = envelope["choices"][0]["message"]["content"]
                parsed = json.loads(content)
            except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise AudioProviderError("音频 Provider 返回非法 JSON") from exc
            if not isinstance(parsed, dict):
                raise AudioProviderError("音频 Provider 结果顶层不是 JSON 对象")
            return parsed
        raise AudioProviderError("音频 Provider 重试耗尽", transient=True)


__all__ = ["AudioProviderError", "AudioAnalysisProvider"]
