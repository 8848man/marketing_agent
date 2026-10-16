"""Replaceable AI generation boundary for a reviewed draft."""

from __future__ import annotations

from typing import Callable, Protocol

from .ai_client import AIClient, create_ai_client
from .prompt_policy import DRAFT_RESPONSE_SCHEMA, DraftPrompt


class DraftGenerator(Protocol):
    def generate(self, provider: str, model: str, api_key: str,
                 prompt: DraftPrompt) -> dict[str, object]: ...


class ProviderDraftGenerator:
    """The production adapter keeps provider setup out of the dashboard service."""

    def __init__(self, client_factory: Callable[[str, str, str], AIClient] = create_ai_client):
        self.client_factory = client_factory

    def generate(self, provider: str, model: str, api_key: str,
                 prompt: DraftPrompt) -> dict[str, object]:
        return self.client_factory(provider, model, api_key).complete_json(
            prompt.system, prompt.user, response_schema=DRAFT_RESPONSE_SCHEMA)
