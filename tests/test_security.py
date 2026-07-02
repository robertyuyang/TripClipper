"""Tests for the safety boundary utilities."""

from __future__ import annotations

from tripclipper.config import ModelConfig
from tripclipper.security import (
    REDACTION,
    redact_secrets,
    summarize_model_config,
)


def test_summarize_model_config_drops_plaintext_secret_from_dict() -> None:
    raw = {
        "provider": "openai_compatible",
        "base_url": "https://api.example.com/v1",
        "api_key_env": "TRIPCLIPPER_MODEL_API_KEY",
        "api_key": "secret123",  # must never appear in summary
        "vision_model": "v",
        "text_model": "t",
        "transcription_model": "a",
    }
    summary = summarize_model_config(raw)
    assert summary["api_key_env"] == "TRIPCLIPPER_MODEL_API_KEY"
    assert "api_key" not in summary
    assert "secret123" not in str(summary)


def test_summarize_model_config_from_model_object() -> None:
    mc = ModelConfig(
        provider="openai_compatible",
        base_url="https://api.example.com/v1",
        api_key_env="KEY_ENV",
        vision_model="v",
    )
    summary = summarize_model_config(mc)
    assert set(summary.keys()) == {
        "provider",
        "base_url",
        "api_key_env",
        "vision_model",
        "text_model",
        "transcription_model",
    }
    assert summary["api_key_env"] == "KEY_ENV"


def test_redact_secrets_removes_explicit_value() -> None:
    out = redact_secrets("api_key=secret123", ["secret123"])
    assert "secret123" not in out
    assert REDACTION in out


def test_redact_secrets_regex_backstop() -> None:
    # Even with no explicit secret list, common patterns are redacted.
    out = redact_secrets('config: {"api_key": "abc-xyz-789"}')
    assert "abc-xyz-789" not in out
    assert REDACTION in out
