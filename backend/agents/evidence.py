"""Evidence verification for free-text fact extraction (P3.6-Rules-Trigger-
Spec.md §5.4). An extracted value only counts as "stated" if the model also
supplied at least one verbatim quote that code independently verifies is
present in the source message -- the model's own claim is never trusted.
"""
from __future__ import annotations

import re
from typing import Optional, Union

from pydantic import BaseModel


def normalise_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def quote_verified(quote: str, message: str) -> bool:
    """True iff `quote` appears verbatim in `message`, tolerant only of
    whitespace/line-break differences (both sides collapsed the same way) --
    never tolerant of paraphrase, since that's exactly the gap between "the
    model said so" and "the message actually says so"."""
    if not quote or not quote.strip():
        return False
    return normalise_whitespace(quote) in normalise_whitespace(message)


class ExtractedValue(BaseModel):
    value: Optional[Union[float, int, bool, str]] = None
    evidence: list[str] = []


class ExtractionResult(BaseModel):
    fields: dict[str, ExtractedValue] = {}


def verify_extraction(result: ExtractionResult, message: str, allowed_fields: set[str]) -> dict[str, dict]:
    """{field: {"value":..., "evidence":[...]}} for every field whose value
    is non-null AND has >=1 verified evidence quote. Everything else --
    missing/empty evidence, an unverifiable (e.g. paraphrased) quote, wrong
    type, or a field name outside the agent's own schema -- is dropped, and
    that field counts as not stated (never a default, never a guess)."""
    verified: dict[str, dict] = {}
    for field, extracted in result.fields.items():
        if field not in allowed_fields:
            continue
        if extracted.value is None:
            continue
        quotes = [q for q in extracted.evidence if quote_verified(q, message)]
        if not quotes:
            continue
        verified[field] = {"value": extracted.value, "evidence": quotes}
    return verified


class MessageTooLongError(RuntimeError):
    """Raised instead of truncating -- P3.6 §5.4 requires the whole message
    reach every agent's extraction, never a chunked/cut-down version."""


def estimate_tokens(text: str) -> int:
    """Conservative, dependency-free estimate (~4 chars/token is a common
    conservative approximation for English prose) -- documented as
    conservative in README; not a real tokenizer, deliberately errs toward
    over-counting so a message that's actually borderline fails clearly
    rather than silently squeaking through and getting truncated by the
    provider instead."""
    return max(1, len(text) // 3)


def assert_within_context(text: str, max_tokens: int) -> None:
    estimated = estimate_tokens(text)
    if estimated > max_tokens:
        raise MessageTooLongError(
            f"Message is ~{estimated} tokens, over the configured MODEL_CONTEXT_TOKENS={max_tokens}. "
            "Consilium never chunks or truncates a message for extraction -- shorten it, or raise "
            "MODEL_CONTEXT_TOKENS if your model's context window genuinely supports it."
        )
