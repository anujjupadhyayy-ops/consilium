from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import find_dotenv, load_dotenv

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

    @classmethod
    def from_env(cls) -> "ModelConfig":
        return cls(
            provider=os.environ.get("MODEL_PROVIDER", "openai"),
            model_name=os.environ.get("MODEL_NAME", "gpt-4o-mini"),
            base_url=os.environ.get("BASE_URL") or None,
            api_key=os.environ.get("API_KEY") or None,
        )
