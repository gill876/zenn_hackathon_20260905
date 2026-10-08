"""
LLM client for GMI Cloud (OpenAI-compatible API).

Async, so a slow model call doesn't block other webhook requests, and capped per day through the usage
counters. Callers always get a dict back; on any failure (cap reached, timeout, bad JSON) it's empty and
the caller falls back to a rule-based answer.
"""

import json
import logging
from typing import Any

from openai import AsyncOpenAI

log = logging.getLogger("llm_client")


class LLMClient:
    def __init__(self, api_key: str, base_url: str, model: str, usage=None, timeout: float = 20.0):
        self.model = model
        self._usage = usage
        self._timeout = timeout
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key or "missing") if api_key else None

    @property
    def available(self) -> bool:
        return self._client is not None

    async def generate_json(self, prompt: str, system_prompt: str, max_tokens: int = 900) -> dict[str, Any]:
        if self._client is None:
            return {}
        if self._usage and not await self._usage.take("llm"):
            log.warning("daily LLM limit reached; using the rule-based fallback")
            return {}
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": f"{system_prompt}\nOutput MUST be a single valid JSON object."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
                temperature=0.2,
                timeout=self._timeout,
            )
            content = (response.choices[0].message.content or "").strip()
        except Exception as e:  # network, timeout, provider errors
            log.error("LLM call failed: %s", e)
            return {}
        return parse_json_object(content)


def parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1:] if "\n" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
