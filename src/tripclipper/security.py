"""Safety boundary utilities (PRD 4.4 / TD 12).

Responsibilities in M0:

- Produce a redacted summary of the model configuration that NEVER contains
  secret material (only the *name* of the env var holding the key).
- Provide a best-effort secret redaction helper for downstream artefacts
  (CSV / Markdown / HTML / logs / Eagle notes).
- Document the read-only constraint on the original source folder; this module
  intentionally exposes no delete / move / copy / overwrite operation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional, Union

REDACTION = "***REDACTED***"

# Keys whose names indicate the value is a secret and must never be summarised.
_SECRET_KEY_NAMES = {
    "api_key",
    "apikey",
    "api-key",
    "key",
    "secret",
    "token",
    "password",
    "passwd",
    "access_token",
    "refresh_token",
}

# Fields that ARE safe to surface in ``model_config_summary``.
_SUMMARY_FIELDS = (
    "provider",
    "base_url",
    "api_key_env",
    "vision_model",
    "text_model",
    "transcription_model",
    "language",
    "sample_size",
)


def _get(obj: Any, name: str) -> Any:
    """Read ``name`` from a dict or an object attribute, tolerating absence."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def summarize_model_config(model_config: Any) -> dict[str, Any]:
    """Return a redacted, secret-free summary of a model configuration.

    Accepts a ``ModelConfig`` (or any object exposing the same attributes) or a
    plain ``dict``. Only the allow-listed, non-secret fields are surfaced. Any
    secret-bearing field (e.g. ``api_key``) present in the input is dropped.
    """
    summary: dict[str, Any] = {}
    for field in _SUMMARY_FIELDS:
        summary[field] = _get(model_config, field)
    return summary


def redact_secrets(text: str, secrets: Optional[list[str]] = None) -> str:
    """Replace secret values in ``text`` with ``***REDACTED***``.

    First replaces any explicitly supplied secret values, then applies a
    best-effort regex pass over common ``key=value`` and ``"key": "value"``
    patterns as a backstop.
    """
    if text is None:
        return text

    result = text

    # 1. Replace explicitly provided secret values.
    if secrets:
        for secret in secrets:
            if secret:
                result = result.replace(str(secret), REDACTION)

    # 2. Regex backstop for common secret-bearing assignment patterns.
    key_alt = "|".join(re.escape(k) for k in sorted(_SECRET_KEY_NAMES, key=len, reverse=True))

    # key="value" / key='value' / key: "value"  (quoted)
    quoted = re.compile(
        rf'(?i)(["\']?(?:{key_alt})["\']?\s*[:=]\s*)(["\'])(.*?)(\2)'
    )
    result = quoted.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTION}{m.group(4)}", result)

    # key=value (unquoted, until whitespace / separator)
    unquoted = re.compile(rf'(?i)\b((?:{key_alt})\s*[:=]\s*)([^\s,;"\']+)')
    result = unquoted.sub(lambda m: f"{m.group(1)}{REDACTION}", result)

    return result


def assert_read_only_source(path: Union[str, Path]) -> Path:
    """Return a read-only reference to a source path.

    The original ``source_folder`` and its media are accessed read-only. This
    module deliberately provides NO delete / move / copy / overwrite operation
    over the source. Callers receive a plain ``Path`` for read access only.
    """
    return Path(path)


__all__ = [
    "REDACTION",
    "summarize_model_config",
    "redact_secrets",
    "assert_read_only_source",
]
