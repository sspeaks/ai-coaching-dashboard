import json
from typing import Any

import httpx

from .config import Settings


class OpenAIClientError(RuntimeError):
    code = "openai_error"


class OpenAITimeoutError(OpenAIClientError):
    code = "openai_timeout"


class OpenAIClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract_json(self, *, messages: list[dict[str, str]], schema: dict[str, Any]) -> Any:
        if not self.settings.openai_api_key:
            raise OpenAIClientError("OpenAI API key is not configured")

        payload = {
            "model": self.settings.openai_model,
            "messages": messages,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "coaching_ledger_entries",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        try:
            with httpx.Client(
                base_url=str(self.settings.openai_base_url).rstrip("/"),
                timeout=self.settings.request_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = client.post(
                    "/chat/completions",
                    headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise OpenAITimeoutError("OpenAI request timed out") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise OpenAIClientError(f"OpenAI request failed: {exc}") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenAIClientError("OpenAI response did not contain message content") from exc

        if isinstance(content, str):
            try:
                return json.loads(content)
            except json.JSONDecodeError as exc:
                raise OpenAIClientError("OpenAI response was not valid JSON") from exc
        if isinstance(content, dict):
            return content
        raise OpenAIClientError("OpenAI response content had an unsupported shape")
