"""
LLM Client powered by GMI Cloud API (OpenAI-compatible)
Using high-speed Qwen3.8-Flash (1M Context)
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("llm_client")

class LLMClient:
    def __init__(self):
        self.api_key = os.getenv("GMI_API_KEY")
        self.base_url = os.getenv("GMI_BASE_URL", "https://api.gmi-serving.com/v1")
        self.model = os.getenv("GMI_MODEL", "Qwen/Qwen3.8-Flash")
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)

    async def generate_json(self, prompt: str, system_prompt: str, max_tokens: int = 450) -> Dict[str, Any]:
        """Generate structured JSON output from LLM with low latency."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": f"{system_prompt}\nOutput MUST be valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
                temperature=0.3,
                timeout=12.0
            )
            content = response.choices[0].message.content or "{}"
            return json.loads(content)
        except Exception as e:
            logger.error(f"GMI LLM JSON generation error: {e}")
            # Try parsing raw text if markdown formatting slipped in
            try:
                raw = response.choices[0].message.content
                cleaned = raw.strip().replace("```json", "").replace("```", "").strip()
                return json.loads(cleaned)
            except Exception:
                return {}

    async def generate_text(self, prompt: str, system_prompt: str) -> str:
        """Generate plain text from LLM."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"GMI LLM text generation error: {e}")
            return "エラーが発生しました。"
