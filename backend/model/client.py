from __future__ import annotations

from typing import Optional

from openai import OpenAI

from .config import ModelConfig


def get_client(config: Optional[ModelConfig] = None) -> OpenAI:
    """Thin, OpenAI-compatible client wrapper. Used from P3.5 onward by
    model/llm.py's structured-call helper -- agent narration, routing, and
    reconciliation all go through this one seam."""
    config = config or ModelConfig.current()
    return OpenAI(base_url=config.base_url, api_key=config.api_key or "not-needed-for-local")
