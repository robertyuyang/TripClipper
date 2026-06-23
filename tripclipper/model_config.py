from __future__ import annotations

import os
from pathlib import Path
from typing import Any


ENV_FILE = ".env"


def load_env_file(path: str | Path | None = None) -> dict[str, str]:
    env_path = Path(path or Path.cwd() / ENV_FILE)
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
            os.environ.setdefault(key, value)
    return values


def global_model_config(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd()).resolve()
    load_env_file(root / ENV_FILE)
    api_key_env = os.environ.get("TRIPCLIPPER_MODEL_API_KEY_ENV", "TRIPCLIPPER_MODEL_API_KEY")
    return {
        "provider": os.environ.get("TRIPCLIPPER_MODEL_PROVIDER", "openai_compatible"),
        "base_url": os.environ.get("TRIPCLIPPER_MODEL_BASE_URL", ""),
        "api_key_env": api_key_env,
        "vision_model": os.environ.get("TRIPCLIPPER_VISION_MODEL", ""),
        "text_model": os.environ.get("TRIPCLIPPER_TEXT_MODEL", os.environ.get("TRIPCLIPPER_VISION_MODEL", "")),
        "transcription_model": os.environ.get("TRIPCLIPPER_TRANSCRIPTION_MODEL", ""),
        "sample_size": _int_env("TRIPCLIPPER_SAMPLE_SIZE", 25),
        "language": os.environ.get("TRIPCLIPPER_MODEL_LANGUAGE", "zh-CN"),
    }


def model_config_status(base_dir: str | Path | None = None) -> dict[str, Any]:
    config = global_model_config(base_dir)
    key_name = str(config.get("api_key_env") or "")
    return {
        "provider": config.get("provider"),
        "base_url": config.get("base_url"),
        "api_key_env": key_name,
        "has_api_key": bool(key_name and os.environ.get(key_name)),
        "vision_model": config.get("vision_model"),
        "text_model": config.get("text_model"),
        "transcription_model": config.get("transcription_model"),
        "sample_size": config.get("sample_size"),
        "language": config.get("language"),
    }


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
