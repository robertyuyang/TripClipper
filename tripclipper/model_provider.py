from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import ssl
import urllib.error
import urllib.request
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .config import validate_model_config
from .constants import PEOPLE_PRESENCE, SHOT_FUNCTIONS, SHOT_SCALES, SUBJECT_TYPES


class ModelProviderError(RuntimeError):
    """Raised when a real model call fails or returns invalid data."""


class ModelConfigurationError(ModelProviderError):
    """Raised when Stage 2 lacks usable real model configuration."""


class ModelProvider(ABC):
    @abstractmethod
    def analyze_asset(self, project: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def transcribe_audio(self, audio_path: str | Path) -> str:
        raise ModelConfigurationError("当前模型 provider 不支持音频转写。")


def create_provider(
    model_config: dict[str, Any] | None,
    *,
    require_analysis_model: bool = True,
    require_transcription_model: bool = False,
) -> ModelProvider:
    errors = validate_model_config(
        model_config,
        require_analysis_model=require_analysis_model,
        require_transcription_model=require_transcription_model,
    )
    if errors:
        raise ModelConfigurationError("；".join(errors))
    config = dict(model_config or {})
    if config.get("provider") == "openai_compatible":
        return OpenAICompatibleProvider(config)
    raise ModelConfigurationError("目前只支持 provider=openai_compatible。")


class OpenAICompatibleProvider(ModelProvider):
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.base_url = str(config["base_url"]).rstrip("/")
        self.api_key = os.environ[str(config["api_key_env"])]
        self.timeout = int(config.get("timeout_seconds") or 120)
        self.language = str(config.get("language") or "zh-CN")

    def analyze_asset(self, project: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
        payload = self._payload(project, asset)
        response = self._post_chat_completions(payload)
        content = _message_content(response)
        raw = _parse_json_content(content)
        return validate_analysis_result(raw)

    def transcribe_audio(self, audio_path: str | Path) -> str:
        model = str(self.config.get("transcription_model") or "").strip()
        if not model:
            raise ModelConfigurationError("model_config.transcription_model 缺失，无法执行音频转写。")
        return self._post_audio_transcriptions(Path(audio_path), model)

    def _payload(self, project: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
        model = self._model_for_asset(asset)
        user_content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": _analysis_prompt(project, asset, self.language),
            }
        ]
        for image_path in _visual_context_paths(asset):
            data_url = _file_to_data_url(image_path)
            if data_url:
                user_content.append({"type": "image_url", "image_url": {"url": data_url}})

        return {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是 TripClipper 的真实素材理解模型。"
                        "你必须只输出结构化 JSON，不要输出 Markdown 或额外解释。"
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            "temperature": float(self.config.get("temperature", 0.2)),
            "response_format": {"type": "json_object"},
        }

    def _model_for_asset(self, asset: dict[str, Any]) -> str:
        if asset.get("type") in {"image", "video"} and self.config.get("vision_model"):
            return str(self.config["vision_model"])
        return str(self.config.get("text_model") or self.config["vision_model"])

    def _post_chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        endpoint = self.base_url
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "TripClipper/0.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=_ssl_context()) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ModelProviderError(f"模型服务返回 HTTP {exc.code}：{body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise ModelProviderError(f"无法连接模型服务：{exc.reason}") from exc
        except TimeoutError as exc:
            raise ModelProviderError("模型服务请求超时。") from exc
        except json.JSONDecodeError as exc:
            raise ModelProviderError("模型服务返回内容不是合法 JSON。") from exc

    def _post_audio_transcriptions(self, audio_path: Path, model: str) -> str:
        endpoint = _audio_transcriptions_endpoint(self.base_url)
        fields = {
            "model": model,
            "response_format": "json",
        }
        language = _transcription_language(self.language)
        if language:
            fields["language"] = language
        boundary, body = _multipart_form_data(fields, "file", audio_path)
        request = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "TripClipper/0.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=_ssl_context()) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise ModelProviderError(f"音频转写服务返回 HTTP {exc.code}：{body_text[:500]}") from exc
        except urllib.error.URLError as exc:
            raise ModelProviderError(f"无法连接音频转写服务：{exc.reason}") from exc
        except TimeoutError as exc:
            raise ModelProviderError("音频转写服务请求超时。") from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            text = raw.strip()
            if text:
                return text
            raise ModelProviderError("音频转写服务返回空文本。")
        text = _transcription_text(payload)
        if not text:
            raise ModelProviderError("音频转写服务响应缺少 text。")
        return text


def validate_analysis_result(raw: dict[str, Any]) -> dict[str, Any]:
    required = [
        "summary",
        "tags",
        "rating",
        "subject_type",
        "primary_subject",
        "people_presence",
        "shot_scale",
        "shot_function",
        "segments",
    ]
    missing = [field for field in required if field not in raw]
    if missing:
        raise ModelProviderError(f"模型输出缺少字段：{', '.join(missing)}")

    result = dict(raw)
    result["summary"] = str(result["summary"]).strip()
    result["tags"] = [str(tag).strip() for tag in _as_list(result["tags"]) if str(tag).strip()]
    result["rating"] = _rating(result["rating"])
    result["subject_type"] = _enum(result["subject_type"], SUBJECT_TYPES, "subject_type")
    result["primary_subject"] = str(result["primary_subject"]).strip()
    result["people_presence"] = _enum(result["people_presence"], PEOPLE_PRESENCE, "people_presence")
    result["shot_scale"] = _enum(result["shot_scale"], SHOT_SCALES, "shot_scale")
    result["shot_function"] = _enum(result["shot_function"], SHOT_FUNCTIONS, "shot_function")
    result["scene"] = str(result.get("scene") or result["primary_subject"] or "").strip()
    result["audio_strategy"] = str(result.get("audio_strategy") or result.get("audio_suggestion") or "needs_review")
    result["audio_suggestion"] = str(result.get("audio_suggestion") or result["audio_strategy"])
    result["segments"] = [_normalize_segment(segment, result) for segment in _as_list(result["segments"])]
    if not result["segments"]:
        raise ModelProviderError("模型输出 segments 为空。")
    return result


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _analysis_prompt(project: dict[str, Any], asset: dict[str, Any], language: str) -> str:
    editing_intent = project.get("editing_intent") or {}
    visual_note = ""
    if not _visual_context_paths(asset):
        visual_note = "当前素材没有可用缩略图或关键帧，请明确基于可见输入的局限性，无法判断时使用 other 或 needs_review。"
    return f"""
请分析这个素材，并输出 {language} 的 JSON。

项目剪辑意图：
{json.dumps(editing_intent, ensure_ascii=False, indent=2)}

素材元数据：
{json.dumps(_asset_prompt_metadata(asset), ensure_ascii=False, indent=2)}

{visual_note}

JSON 字段必须包含：
- summary: 中文素材说明
- tags: 字符串数组，包含内容、用途、声音或质量标签
- rating: 1 到 5 的整数
- scene: 场景短名
- subject_type: landscape/people/people_landscape/food/building/activity/object/other
- primary_subject: 主要主体的中文描述
- people_presence: none/single/multiple/small_group/crowd
- shot_scale: extreme_wide/wide/full/medium/close_up/extreme_close_up
- shot_function: establishing/highlight/transition/detail/reaction/dialogue/b_roll/other
- segments: 数组，每项含 in、out、role、subject_type、shot_scale、rating、reason、audio_strategy、tags
- audio_suggestion: 中文声音建议
- audio_strategy: keep_voice/keep_ambient/mute_or_low_ambient/replace_music/needs_review 等短枚举或短语

请不要编造看不见的内容；无法可靠判断时使用 other、needs_review，并在 summary 或 reason 中说明不确定性。
""".strip()


def _asset_prompt_metadata(asset: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        "asset_id": asset.get("asset_id"),
        "file": asset.get("file"),
        "relative_path": asset.get("relative_path"),
        "type": asset.get("type"),
        "extension": asset.get("extension"),
        "size": asset.get("size"),
        "modified_time": asset.get("modified_time"),
        "metadata": asset.get("metadata") or {},
    }
    transcript = _transcript_excerpt(asset.get("transcript_path"))
    if transcript:
        metadata["transcript_path"] = asset.get("transcript_path")
        metadata["transcript_excerpt"] = transcript
    return metadata


def _audio_transcriptions_endpoint(base_url: str) -> str:
    endpoint = base_url.rstrip("/")
    if endpoint.endswith("/chat/completions"):
        endpoint = endpoint[: -len("/chat/completions")]
    if not endpoint.endswith("/audio/transcriptions"):
        endpoint = f"{endpoint}/audio/transcriptions"
    return endpoint


def _multipart_form_data(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[str, bytes]:
    boundary = f"----TripClipper{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")

    mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        (
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(file_path.read_bytes())
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return boundary, b"".join(chunks)


def _transcription_language(language: str) -> str | None:
    token = re.split(r"[-_]", str(language or "").strip().lower(), maxsplit=1)[0]
    if not token or token in {"auto", "default"}:
        return None
    return token


def _transcription_text(payload: Any) -> str:
    if isinstance(payload, dict):
        if payload.get("text"):
            return str(payload["text"]).strip()
        segments = payload.get("segments")
        if isinstance(segments, list):
            return "".join(str(segment.get("text") or "") for segment in segments if isinstance(segment, dict)).strip()
    return ""


def _transcript_excerpt(raw_path: Any, limit: int = 6000) -> str | None:
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if not path.exists() or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...（转写文本已截断，仅用于模型上下文）"


def _visual_context_paths(asset: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for raw in asset.get("frame_paths") or []:
        path = Path(str(raw))
        if path.exists() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            paths.append(path)
    return paths[:4]


def _file_to_data_url(path: Path) -> str | None:
    if path.stat().st_size > 8 * 1024 * 1024:
        return None
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(path.suffix.lower())
    if not mime:
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _message_content(response: dict[str, Any]) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelProviderError("模型服务响应缺少 choices[0].message.content。") from exc
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content)


def _parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ModelProviderError("模型输出不是合法 JSON 对象。") from exc
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ModelProviderError("模型输出必须是 JSON 对象。")
    return value


def _rating(value: Any) -> int:
    try:
        rating = int(value)
    except (TypeError, ValueError) as exc:
        raise ModelProviderError("rating 必须是 1 到 5 的整数。") from exc
    if rating < 1 or rating > 5:
        raise ModelProviderError("rating 必须在 1 到 5 之间。")
    return rating


def _enum(value: Any, allowed: set[str], field: str) -> str:
    text = str(value).strip()
    if text not in allowed:
        raise ModelProviderError(f"{field} 的值不合法：{text}")
    return text


def _normalize_segment(segment: Any, asset_result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(segment, dict):
        raise ModelProviderError("segments 中的每一项必须是对象。")
    return {
        "in": str(segment.get("in") or "00:00:00"),
        "out": str(segment.get("out") or segment.get("in") or "00:00:00"),
        "role": str(segment.get("role") or asset_result["shot_function"]),
        "subject_type": _enum(segment.get("subject_type") or asset_result["subject_type"], SUBJECT_TYPES, "segment.subject_type"),
        "shot_scale": _enum(segment.get("shot_scale") or asset_result["shot_scale"], SHOT_SCALES, "segment.shot_scale"),
        "rating": _rating(segment.get("rating") or asset_result["rating"]),
        "reason": str(segment.get("reason") or asset_result["summary"]),
        "audio_strategy": str(segment.get("audio_strategy") or asset_result["audio_strategy"]),
        "tags": [str(tag).strip() for tag in _as_list(segment.get("tags") or asset_result["tags"]) if str(tag).strip()],
    }


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
