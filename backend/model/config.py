from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import find_dotenv, load_dotenv

from .runtime_settings import read_runtime_settings

load_dotenv(find_dotenv(usecwd=True))


@dataclass(frozen=True)
class ModelConfig:
    """OpenAI-compatible model config, sourced only from env.

    provider/model_name are carried for P2's agents to pass into
    client.chat.completions.create(...) -- no provider branching lives here,
    since "OpenAI-compatible" (base_url swap) is the whole point: it covers
    OpenAI, Anthropic-via-compatible-gateway, and self-hosted OSS models
    (Kimi, Qwen, Llama) alike.
    """

    provider: str
    model_name: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    # P3.6: a conservative, editable ceiling on how large a free-text message
    # extraction will accept. Never used to truncate -- a message estimated
    # over this raises a clear error instead (see agents/evidence.py).
    context_tokens: int = 8000

    @classmethod
    def from_env(cls) -> "ModelConfig":
        return cls(
            provider=os.environ.get("MODEL_PROVIDER", "openai"),
            model_name=os.environ.get("MODEL_NAME", "gpt-4o-mini"),
            base_url=os.environ.get("BASE_URL") or None,
            api_key=os.environ.get("API_KEY") or None,
            context_tokens=int(os.environ.get("MODEL_CONTEXT_TOKENS", "8000")),
        )

    @classmethod
    def current(cls) -> "ModelConfig":
        """env, overridden by whatever Settings has saved at runtime."""
        base = cls.from_env()
        saved = read_runtime_settings()
        return cls(
            provider=saved.get("provider", base.provider),
            model_name=saved.get("model_name", base.model_name),
            base_url=saved.get("base_url", base.base_url),
            api_key=saved.get("api_key", base.api_key),
            context_tokens=saved.get("context_tokens", base.context_tokens),
        )
