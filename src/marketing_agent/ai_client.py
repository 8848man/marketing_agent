"""Provider adapters behind the JSON completion contract."""

import json
import os
import re
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .http_client import ResponseTooLarge, opener, read_limited


class AIClient(Protocol):
    def complete_json(self, system: str, prompt: str, *, response_schema: dict | None = None) -> dict[str, Any]: ...


PROVIDER_DETAILS = {
    "openai": {"label": "GPT · OpenAI", "default_model": "gpt-5.4-mini", "key_env": "OPENAI_API_KEY",
               "presets": (("gpt-5.4-mini", "GPT-5.4 mini · 균형"), ("gpt-5-mini", "GPT-5 mini · 빠른 초안"), ("gpt-5-nano", "GPT-5 nano · 저비용"))},
    "gemini": {"label": "Gemini · Google", "default_model": "gemini-3.5-flash", "key_env": "GEMINI_API_KEY",
               "presets": (("gemini-3.5-flash", "Gemini 3.5 Flash · 균형"), ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite · 저비용"), ("gemini-2.5-flash", "Gemini 2.5 Flash · 기존 계정용"))},
    "claude": {"label": "Claude · Anthropic", "default_model": "claude-sonnet-4-6", "key_env": "ANTHROPIC_API_KEY",
               "presets": (("claude-sonnet-4-6", "Claude Sonnet 4.6 · 균형"), ("claude-haiku-4-5", "Claude Haiku 4.5 · 빠른 초안"))},
    "grok": {"label": "Grok · xAI", "default_model": "grok-4.7", "key_env": "XAI_API_KEY",
             "presets": (("grok-4.7", "Grok 4.7 · 균형"), ("grok-4-1-fast-reasoning", "Grok 4.1 Fast Reasoning · 빠른 초안"), ("grok-4-1-fast-non-reasoning", "Grok 4.1 Fast Non-reasoning · 저비용"))},
}
PROVIDERS = {name: (details["default_model"], details["key_env"])
             for name, details in PROVIDER_DETAILS.items()}
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
MAX_RESPONSE = 1_000_000
MAX_STRUCTURED_OUTPUT_TOKENS = 512
GEMINI_MAX_GENERATION_TOKENS = 4096
JSON_SCHEMA_TYPES = {"object": "OBJECT", "array": "ARRAY", "string": "STRING",
                     "number": "NUMBER", "integer": "INTEGER", "boolean": "BOOLEAN"}
GEMINI_UNSUPPORTED_SCHEMA_KEYS = frozenset({"additionalProperties"})


_opener = opener()


def _transport(request: Request, *, timeout: int):
    return _opener.open(request, timeout=timeout)


def _response_json(request: Request, transport: Callable) -> dict:
    try:
        with transport(request, timeout=20) as response:
            try:
                raw = read_limited(response, MAX_RESPONSE)
            except TypeError:
                raise ValueError("AI_TRANSPORT_INVALID") from None
    except HTTPError as exc:
        if exc.code in {301, 302, 303, 307, 308}:
            code = "AI_REDIRECT_BLOCKED"
        elif exc.code in {401, 403}:
            code = "AI_AUTH_FAILED"
        elif exc.code == 404:
            code = "AI_MODEL_UNAVAILABLE"
        elif exc.code == 429:
            code = "AI_RATE_LIMITED"
        else:
            code = "AI_PROVIDER_FAILED"
        raise ValueError(code) from None
    except ResponseTooLarge:
        raise ValueError("AI_RESPONSE_TOO_LARGE") from None
    except (OSError, URLError, TimeoutError):
        raise ValueError("AI_NETWORK_FAILED") from None
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("AI_RESPONSE_INVALID") from None
    if not isinstance(result, dict):
        raise ValueError("AI_RESPONSE_INVALID")
    return result


def _parse_json_text(content: str) -> dict[str, Any]:
    if not isinstance(content, str):
        raise ValueError("AI_RESPONSE_INVALID")
    content = content.strip()
    if not content:
        raise ValueError("AI_EMPTY_RESPONSE")
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(content)
    except ValueError:
        parsed = _extract_embedded_json_object(content)
    if not isinstance(parsed, dict):
        raise ValueError("AI_RESPONSE_INVALID")
    return parsed


def _extract_embedded_json_object(content: str) -> dict[str, Any]:
    """Recover one JSON object from otherwise explanatory model text.

    Providers occasionally add a short preface despite structured-output
    settings.  We accept exactly one outer object and leave semantic checks to
    the caller; two separate objects or malformed text remain invalid.
    """
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    covered_until = 0
    for offset, character in enumerate(content):
        if character != "{" or offset < covered_until:
            continue
        try:
            candidate, consumed = decoder.raw_decode(content[offset:])
        except ValueError:
            continue
        covered_until = offset + consumed
        if isinstance(candidate, dict):
            objects.append(candidate)
    if len(objects) != 1:
        raise ValueError("AI_RESPONSE_INVALID")
    return objects[0]


def _required_schema(response_schema: dict | None) -> dict | None:
    """Accept only an object JSON Schema when a caller requires structured output."""
    if response_schema is None:
        return None
    if (not isinstance(response_schema, dict) or response_schema.get("type") != "object"
            or not isinstance(response_schema.get("properties"), dict)
            or not isinstance(response_schema.get("required"), list)):
        raise ValueError("AI_SCHEMA_INVALID")
    return response_schema


def _gemini_schema(value: Any) -> Any:
    """Convert to Generate Content's OpenAPI schema subset.

    The application still validates the complete shared contract after the
    response.  `additionalProperties` is rejected by the legacy
    `generationConfig.responseSchema` endpoint, so it must not be sent.
    """
    if isinstance(value, list):
        return [_gemini_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    translated = {key: _gemini_schema(item) for key, item in value.items()
                  if key not in GEMINI_UNSUPPORTED_SCHEMA_KEYS}
    kind = translated.get("type")
    if isinstance(kind, str) and kind in JSON_SCHEMA_TYPES:
        translated["type"] = JSON_SCHEMA_TYPES[kind]
    return translated


def validate_model(model: str) -> str:
    if not isinstance(model, str) or not MODEL_ID.fullmatch(model):
        raise ValueError("AI_MODEL_INVALID")
    return model


class ClaudeClient:
    def __init__(self, api_key: str | None = None, *, model: str = "claude-sonnet-4-5", transport: Callable | None = None):
        self.api_key = api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY")
        self.model = validate_model(model)
        self.transport = transport or _transport

    def complete_json(self, system: str, prompt: str, *, response_schema: dict | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise ValueError("AI_KEY_MISSING")
        schema = _required_schema(response_schema)
        body = {"model": self.model, "max_tokens": MAX_STRUCTURED_OUTPUT_TOKENS, "system": system,
                "messages": [{"role": "user", "content": prompt}]}
        if schema is not None:
            body["tools"] = [{
                "name": "return_structured_response",
                "description": "Return the requested response fields using this schema.",
                "input_schema": schema,
            }]
            body["tool_choice"] = {"type": "tool", "name": "return_structured_response"}
        request = Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"}, method="POST",
        )
        payload = _response_json(request, self.transport)
        if schema is not None:
            for block in payload.get("content", []):
                if (isinstance(block, dict) and block.get("type") == "tool_use"
                        and block.get("name") == "return_structured_response"
                        and isinstance(block.get("input"), dict)):
                    return block["input"]
            raise ValueError("AI_RESPONSE_SCHEMA_INVALID")
        content = "".join(block.get("text", "") for block in payload.get("content", [])
                          if isinstance(block, dict) and block.get("type") == "text")
        return _parse_json_text(content)


class ResponsesClient:
    """OpenAI and xAI Responses adapters share a request/response shape."""

    def __init__(self, api_key: str, *, model: str, provider: str,
                 transport: Callable | None = None):
        if provider not in {"openai", "grok"}:
            raise ValueError("AI_PROVIDER_INVALID")
        self.api_key = api_key
        self.model = validate_model(model)
        self.provider = provider
        self.transport = transport or _transport

    def complete_json(self, system: str, prompt: str, *, response_schema: dict | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise ValueError("AI_KEY_MISSING")
        schema = _required_schema(response_schema)
        host = "api.openai.com" if self.provider == "openai" else "api.x.ai"
        body = {"model": self.model, "input": [
            {"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "max_output_tokens": MAX_STRUCTURED_OUTPUT_TOKENS}
        if self.provider == "openai":
            body["store"] = False
        if schema is not None:
            body["text"] = {"format": {"type": "json_schema", "name": "structured_response",
                                        "strict": True, "schema": schema}}
        request = Request(f"https://{host}/v1/responses",
                          data=json.dumps(body).encode("utf-8"),
                          headers={"Authorization": f"Bearer {self.api_key}",
                                   "Content-Type": "application/json"}, method="POST")
        payload = _response_json(request, self.transport)
        chunks = [part.get("text", "") for item in payload.get("output", [])
                  if isinstance(item, dict) and item.get("type") == "message"
                  for part in item.get("content", [])
                  if isinstance(part, dict) and part.get("type") == "output_text"]
        return _parse_json_text("".join(chunks))


class GeminiClient:
    def __init__(self, api_key: str, *, model: str, transport: Callable | None = None):
        self.api_key = api_key
        self.model = validate_model(model)
        self.transport = transport or _transport

    def complete_json(self, system: str, prompt: str, *, response_schema: dict | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise ValueError("AI_KEY_MISSING")
        # Gemini 3 counts thought tokens against maxOutputTokens. A 1,024
        # token cap can cut off a tiny JSON answer before it is complete.
        config = {"maxOutputTokens": GEMINI_MAX_GENERATION_TOKENS, "responseMimeType": "application/json"}
        if self.model.startswith("gemini-3"):
            config["thinkingConfig"] = {"thinkingLevel": "LOW"}
        schema = _required_schema(response_schema)
        if schema is not None:
            config["responseSchema"] = _gemini_schema(schema)
        request = Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            data=json.dumps({"systemInstruction": {"parts": [{"text": system}]},
                             "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                             "generationConfig": config}).encode("utf-8"),
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            method="POST")
        payload = _response_json(request, self.transport)
        candidates = payload.get("candidates", [])
        if not isinstance(candidates, list):
            raise ValueError("AI_RESPONSE_INVALID")
        if any(isinstance(candidate, dict) and candidate.get("finishReason") == "MAX_TOKENS"
               for candidate in candidates):
            raise ValueError("AI_RESPONSE_TRUNCATED")
        chunks = [part.get("text", "") for candidate in candidates
                  if isinstance(candidate, dict)
                  for part in candidate.get("content", {}).get("parts", [])
                  if isinstance(part, dict)]
        return _parse_json_text("".join(chunks))


_CLIENT_FACTORIES: dict[str, Callable[[str, str, Callable | None], AIClient]] = {
    "openai": lambda key, model, transport: ResponsesClient(key, model=model, provider="openai", transport=transport),
    "grok": lambda key, model, transport: ResponsesClient(key, model=model, provider="grok", transport=transport),
    "gemini": lambda key, model, transport: GeminiClient(key, model=model, transport=transport),
    "claude": lambda key, model, transport: ClaudeClient(key, model=model, transport=transport),
}


def register_ai_provider(name: str, *, label: str, default_model: str,
                         key_env: str, presets: tuple[tuple[str, str], ...],
                         factory: Callable[[str, str, Callable | None], AIClient]) -> None:
    """Register a trusted adapter for settings, the UI, and draft generation."""
    if (not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name)
            or name in PROVIDERS or not isinstance(label, str) or not label.strip()
            or not isinstance(key_env, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*_API_KEY", key_env)
            or not callable(factory) or not presets or presets[0][0] != default_model):
        raise ValueError("AI_PROVIDER_INVALID")
    validate_model(default_model)
    if any(not isinstance(item, tuple) or len(item) != 2 or
           validate_model(item[0]) != item[0] or not isinstance(item[1], str) or not item[1].strip()
           for item in presets):
        raise ValueError("AI_PROVIDER_INVALID")
    details = {"label": label, "default_model": default_model,
               "key_env": key_env, "presets": presets}
    PROVIDER_DETAILS[name] = details
    PROVIDERS[name] = (default_model, key_env)
    _CLIENT_FACTORIES[name] = factory


def create_ai_client(provider: str, model: str, api_key: str,
                     *, transport: Callable | None = None) -> AIClient:
    factory = _CLIENT_FACTORIES.get(provider)
    if factory is None:
        raise ValueError("AI_PROVIDER_INVALID")
    return factory(api_key, validate_model(model), transport)


def test_ai_connection(provider: str, model: str, api_key: str,
                       *, transport: Callable | None = None) -> bool:
    client = create_ai_client(provider, model, api_key, transport=transport)
    schema = {"type": "object", "properties": {
        "worry_summary": {"type": "string"}, "cited_detail": {"type": "string"},
        "comment": {"type": "string"}},
        "required": ["worry_summary", "cited_detail", "comment"],
        "additionalProperties": False}
    result = client.complete_json(
        "Reply only with the requested JSON object.",
        "Connection check. Return a Korean draft using this evidence: 연애 고민. "
        "Set cited_detail to the exact phrase 연애 고민, and provide non-empty "
        "worry_summary and comment fields.", response_schema=schema)
    if (set(result) != {"worry_summary", "cited_detail", "comment"}
            or any(not isinstance(value, str) or not value.strip() for value in result.values())):
        raise ValueError("AI_RESPONSE_SCHEMA_INVALID")
    return True
