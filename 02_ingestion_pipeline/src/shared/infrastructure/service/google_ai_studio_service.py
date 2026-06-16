"""Google AI Studio async service."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import requests

from shared.infrastructure.setting import GoogleAIStudioSetting


PROMPT_TEMPLATE = """
You are a data extraction assistant.
Return only valid JSON.

Input items:
{items}

Required output shape:
{{
  "data": []
}}
"""


class GoogleAIStudioService:
    """Async client for Google AI Studio Generative Language API."""

    def __init__(self, setting: GoogleAIStudioSetting | None = None) -> None:
        self.setting = setting or GoogleAIStudioSetting()

    async def generate_json(
        self,
        items: list[str],
        prompt_template: str = PROMPT_TEMPLATE,
    ) -> dict[str, Any]:
        """
        Send a prompt and list of strings to Google AI Studio, expecting JSON data.

        Args:
            items: List of strings to include in the prompt.
            prompt_template: Prompt template containing an `{items}` placeholder.

        Returns:
            Parsed JSON response. If model returns a raw list, it is wrapped as
            `{"data": raw_list}`.
        """
        prompt = self._build_prompt(prompt_template=prompt_template, items=items)
        payload = self._build_payload(prompt)
        response_json = await asyncio.to_thread(self._post_generate_content, payload)
        text = self._extract_text(response_json)
        parsed_json = self._parse_json_text(text)
        return self._normalize_response(parsed_json)

    def _build_prompt(self, prompt_template: str, items: list[str]) -> str:
        items_json = json.dumps(items, ensure_ascii=False, indent=2)
        return prompt_template.format(items=items_json)

    def _build_payload(self, prompt: str) -> dict[str, Any]:
        return {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
            },
        }

    def _post_generate_content(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.setting.google_ai_studio_api_key:
            raise RuntimeError("GOOGLE_AI_STUDIO_API_KEY is required")

        url = (
            f"{self.setting.google_ai_studio_base_url}/v1beta/models/"
            f"{self.setting.google_ai_studio_model}:generateContent"
        )
        response = requests.post(
            url,
            params={"key": self.setting.google_ai_studio_api_key},
            json=payload,
            timeout=self.setting.google_ai_studio_timeout,
        )
        response.raise_for_status()
        return response.json()

    def _extract_text(self, response_json: dict[str, Any]) -> str:
        candidates = response_json.get("candidates", [])
        if not candidates:
            raise RuntimeError("Google AI Studio returned no candidates")

        parts = candidates[0].get("content", {}).get("parts", [])
        text_parts = [part.get("text", "") for part in parts if part.get("text")]
        text = "".join(text_parts).strip()
        if not text:
            raise RuntimeError("Google AI Studio returned empty text")
        return text

    def _parse_json_text(self, text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Google AI Studio response is not valid JSON: {text}") from exc

    def _normalize_response(self, parsed_json: Any) -> dict[str, Any]:
        if isinstance(parsed_json, dict):
            if "data" not in parsed_json:
                return {"data": parsed_json}
            return parsed_json
        return {"data": parsed_json}


google_ai_studio_service = GoogleAIStudioService()


async def sayhello() -> dict[str, Any]:
    """Call Google AI Studio and ask it to return a hello message as JSON."""
    prompt_template = """
Return only valid JSON.
Say hello in a friendly way.

Input items:
{items}

Required output shape:
{{
  "data": {{
    "message": ""
  }}
}}
"""
    return await google_ai_studio_service.generate_json(
        items=["say hello"],
        prompt_template=prompt_template,
    )


async def main() -> None:
    """Run a smoke test against Google AI Studio."""
    from shared.utils.logging import info

    result = await sayhello()
    info(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
