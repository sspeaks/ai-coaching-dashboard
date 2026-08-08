import copy
import json
from typing import Any

import httpx

from .config import Settings

# Keywords OpenAI's strict structured-output mode rejects outright.
_UNSUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "default",
        "examples",
        "format",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "multipleOf",
        "pattern",
        "patternProperties",
        "propertyNames",
        "uniqueItems",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)


def to_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a Pydantic JSON schema so OpenAI strict structured outputs accept it.

    Strict mode demands that every object list all of its properties in ``required``
    and set ``additionalProperties: false``. Free-form maps cannot be expressed at
    all, so they are dropped; the gateway fills ``extraction_metadata`` itself.
    Validation keywords such as ``minItems`` are unsupported and are stripped -- the
    gateway still enforces them when it validates the model's response.
    """

    def rewrite(node: Any) -> Any:
        if isinstance(node, list):
            return [rewrite(item) for item in node]
        if not isinstance(node, dict):
            return node

        result: dict[str, Any] = {
            key: rewrite(value)
            for key, value in node.items()
            if key not in _UNSUPPORTED_SCHEMA_KEYWORDS
        }

        properties = result.get("properties")
        if isinstance(properties, dict):
            # Open maps (additionalProperties: true) have no strict-mode equivalent.
            properties = {
                name: value
                for name, value in properties.items()
                if not _is_open_map(node["properties"][name])
            }
            result["properties"] = properties
            result["required"] = list(properties)
            result["additionalProperties"] = False
        elif result.get("type") == "object":
            result["additionalProperties"] = False
        return result

    return rewrite(copy.deepcopy(schema))


def _is_open_map(node: Any) -> bool:
    return (
        isinstance(node, dict)
        and node.get("type") == "object"
        and "properties" not in node
        and node.get("additionalProperties") is not False
    )


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
                    "schema": to_strict_schema(schema),
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
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise OpenAIClientError(
                f"OpenAI request failed with HTTP {exc.response.status_code}: {detail}"
            ) from exc
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
