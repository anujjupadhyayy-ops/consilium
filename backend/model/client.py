from __future__ import annotations

from typing import Optional

from openai import OpenAI

from .config import ModelConfig


def get_client(config: Optional[ModelConfig] = None) -> OpenAI:
    """Thin, OpenAI-compatible client wrapper.

    Not called by any P1 code path -- P1's stub agents are hard-coded (see
    agents/base.py). Built now, per the kickoff spec ("wire the model layer
    ... use later"), so P2 can start calling this directly without rework.
    """
    config = config or ModelConfig.from_env()
    return OpenAI(base_url=config.base_url, api_key=config.api_key or "not-needed-for-local")
