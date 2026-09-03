"""
Thin wrapper around the Anthropic SDK. Every call goes through here so
cost/latency logging (Part B.7's llm_call_log) happens in exactly one
place instead of being duplicated in every agent.

Pricing table is illustrative — check current pricing before trusting
cost_usd numbers for a real budget: https://docs.claude.com
"""
from __future__ import annotations

import json
import os
import time
from decimal import Decimal
from typing import Any, Optional

import anthropic
from sqlalchemy.orm import Session

from db.repositories import ObservabilityRepository

# USD per 1M tokens, illustrative — update from current pricing docs.
_PRICE_PER_MTOK = {
    "claude-sonnet-4-6": {"input": Decimal("3.00"), "output": Decimal("15.00")},
}
_DEFAULT_MODEL = "claude-sonnet-4-6"


class LLMClient:
    def __init__(self, model: str = _DEFAULT_MODEL):
        self.model = model
        self._client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    def call_json(self, *, system: str, user: str, session: Session,
                   stage: str, document_id: Optional[int], max_tokens: int = 1024) -> dict[str, Any]:
        """Call the model, expecting a JSON object back, and log the call."""
        start = time.monotonic()
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        text = "".join(block.text for block in response.content if block.type == "text")
        cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(cleaned)

        prices = _PRICE_PER_MTOK.get(self.model, _PRICE_PER_MTOK[_DEFAULT_MODEL])
        cost = (
            Decimal(response.usage.input_tokens) * prices["input"]
            + Decimal(response.usage.output_tokens) * prices["output"]
        ) / Decimal(1_000_000)

        ObservabilityRepository(session).log_call(
            stage=stage,
            document_id=document_id,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost,
        )
        return parsed
