"""The one seam every LLM call in Consilium goes through: routing,
per-agent narration, and reconciliation all call `call_structured()`.
Mock this single function in tests rather than mocking the OpenAI client
directly -- see tests/test_chief_of_staff.py.
"""
from __future__ import annotations

import json
from typing import Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from .client import get_client
from .config import ModelConfig

T = TypeVar("T", bound=BaseModel)


class LLMUnavailableError(RuntimeError):
    """The model couldn't be reached, or replied with something that
    doesn't parse -- callers fall back to deterministic behaviour rather
    than let a run crash on a flaky/local model. This is the guardrail
    that keeps 'genuine reasoning' from becoming 'fragile reasoning'."""


def call_structured(
    system: str,
    user: str,
    response_model: Type[T],
    config: Optional[ModelConfig] = None,
    temperature: float = 0.2,
) -> T:
    config = config or ModelConfig.current()
    client = get_client(config)

    kwargs = dict(
        model=config.model_name,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
    )
    try:
        try:
            completion = client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
        except Exception:
            # Not every OpenAI-compatible endpoint honours response_format
            # (verified against a local Ollama server) -- retry bare rather
            # than fail a run over a param the system prompt already asks for.
            completion = client.chat.completions.create(**kwargs)
        content = completion.choices[0].message.content or ""
    except Exception as exc:
        raise LLMUnavailableError(
            f"Could not reach model '{config.model_name}' at {config.base_url or 'the default endpoint'}: {exc}"
        ) from exc

    try:
        payload = json.loads(_extract_json(content))
        return response_model.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMUnavailableError(f"Model response didn't match the expected shape: {exc}") from exc


def _extract_json(text: str) -> str:
    """Some local models wrap JSON in prose or a code fence despite being
    told not to -- take the outermost {...} block as a pragmatic rescue."""
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def test_connection(config: Optional[ModelConfig] = None) -> tuple[bool, str]:
    """Settings' 'Save & test connection' -- one minimal real call."""
    config = config or ModelConfig.current()
    try:
        client = get_client(config)
        client.chat.completions.create(
            model=config.model_name,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            max_tokens=5,
        )
        return True, f"Connected to '{config.model_name}' at {config.base_url or 'the default endpoint'}."
    except Exception as exc:
        return False, str(exc)
