"""
LLM client: Gemini on Vertex AI first, GMI Cloud as the fallback. Both speak the OpenAI-compatible API.

Async, so a slow model call doesn't block other webhook requests, and capped per day through the usage
counters. Callers always get a dict back; on any failure (cap reached, every provider down, bad JSON) it's
empty and the caller falls back to a rule-based answer.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from openai import AsyncOpenAI

log = logging.getLogger("llm_client")

VERTEX_URL = "https://aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/endpoints/openapi"


@dataclass
class Provider:
    name: str
    client: AsyncOpenAI
    model: str


def google_token() -> Callable[[], Awaitable[str]]:
    """An access token from the service account Cloud Run gives us (or local gcloud credentials), refreshed
    when it expires. No key is stored anywhere."""
    creds = None

    async def token() -> str:
        nonlocal creds
        import google.auth
        import google.auth.transport.requests
        if creds is None:
            creds, _ = await asyncio.to_thread(google.auth.default, scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if not creds.valid:
            await asyncio.to_thread(creds.refresh, google.auth.transport.requests.Request())
        return creds.token

    return token


class LLMClient:
    def __init__(self, providers: list[Provider], usage=None, timeout: float = 20.0):
        self.providers = providers
        self._usage = usage
        self._timeout = timeout

    @classmethod
    def from_settings(cls, s, usage=None) -> "LLMClient":
        providers = []
        if s.vertex_project:
            base = VERTEX_URL.format(project=s.vertex_project, location=s.vertex_location)
            providers.append(Provider("vertex", AsyncOpenAI(base_url=base, api_key=google_token()), s.vertex_model))
        if s.gmi_api_key:
            providers.append(Provider("gmi", AsyncOpenAI(base_url=s.gmi_base_url, api_key=s.gmi_api_key), s.gmi_model))
        return cls(providers, usage)

    @property
    def available(self) -> bool:
        return bool(self.providers)

    @property
    def model(self) -> str:
        return self.providers[0].model if self.providers else ""

    async def generate_json(self, prompt: str, system_prompt: str, max_tokens: int = 900) -> dict[str, Any]:
        if not self.providers:
            return {}
        if self._usage and not await self._usage.take("llm"):
            log.warning("daily LLM limit reached; using the rule-based fallback")
            return {}
        messages = [
            {"role": "system", "content": f"{system_prompt}\nOutput MUST be a single valid JSON object."},
            {"role": "user", "content": prompt},
        ]
        for p in self.providers:
            started = time.monotonic()
            try:
                response = await p.client.chat.completions.create(
                    model=p.model, messages=messages, response_format={"type": "json_object"},
                    max_tokens=max_tokens, temperature=0.2, timeout=self._timeout,
                )
                content = (response.choices[0].message.content or "").strip()
            except Exception as e:  # network, timeout, auth, provider errors: try the next provider
                log.error("LLM call failed on %s (%s): %s", p.name, p.model, e)
                continue
            log.info("LLM call served by %s (%s) in %.1fs", p.name, p.model, time.monotonic() - started)
            return parse_json_object(content)
        return {}


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
