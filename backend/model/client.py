from __future__ import annotations

from typing import Optional

from openai import OpenAI

from .config import ModelConfig


def get_client(config: Optional[ModelConfig] = None, timeout: Optional[float] = None) -> OpenAI:
    """Thin, OpenAI-compatible client wrapper. Used from P3.5 onward by
    model/llm.py's structured-call helper -- per-agent extraction, narration,
    and reconciliation all go through this one seam. ``timeout`` is used by the
    cheap status probe so a page-load banner never hangs on a dead endpoint."""
    config = config or ModelConfig.current()
    kwargs = dict(base_url=config.base_url, api_key=config.api_key or "not-needed-for-local")
    if timeout is not None:
        kwargs["timeout"] = timeout
    return OpenAI(**kwargs)
