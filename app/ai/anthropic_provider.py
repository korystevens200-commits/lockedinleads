"""
Anthropic (Claude) provider.

The SDK is imported lazily so the whole application still runs — and demos —
with no AI dependency installed. If the call fails for any reason the engine
falls back to the rules provider rather than leaving a lead unanswered.
"""

import json

from .. import config
from .prompt import OUTPUT_SCHEMA, conversation_messages, system_prompt
from .provider import AIProvider, AITurn


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self):
        self._client = None
        self._sdk_error = ""

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not config.ANTHROPIC_API_KEY:
            self._sdk_error = "ANTHROPIC_API_KEY is not set"
            return None
        try:
            import anthropic
        except ImportError:
            self._sdk_error = "the `anthropic` package is not installed (pip install -r requirements.txt)"
            return None
        self._client = anthropic.Anthropic(
            api_key=config.ANTHROPIC_API_KEY,
            timeout=config.AI_TIMEOUT_SECONDS,
            max_retries=2,
        )
        return self._client

    def available(self) -> bool:
        return self._get_client() is not None

    def generate(self, ctx, directive="reply", incoming=None) -> AITurn:
        client = self._get_client()
        if client is None:
            return AITurn(reply="", provider=self.name, error=self._sdk_error or "unavailable")

        try:
            response = client.messages.create(
                model=config.AI_MODEL,
                max_tokens=config.AI_MAX_TOKENS,
                system=system_prompt(ctx, directive),
                messages=conversation_messages(ctx, incoming),
                output_config={
                    "effort": config.AI_EFFORT,
                    "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
                },
            )
        except Exception as exc:                     # network, auth, rate limit, refusal
            return AITurn(reply="", provider=self.name, error=f"{type(exc).__name__}: {exc}")

        if getattr(response, "stop_reason", None) == "refusal":
            return AITurn(reply="", provider=self.name, error="model declined to respond")

        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            data = json.loads(text)
        except ValueError:
            # Structured output should make this impossible; treat any prose as
            # the reply rather than dropping a customer message on the floor.
            return AITurn(reply=text.strip()[:1000], provider=self.name) if text.strip() else \
                AITurn(reply="", provider=self.name, error="empty response")

        updates = {}
        for item in data.get("qualification_updates") or []:
            if isinstance(item, dict) and item.get("key"):
                updates[str(item["key"])[:40]] = str(item.get("value", ""))[:300]

        return AITurn(
            reply=str(data.get("reply", "")).strip()[:1000],
            intent=data.get("intent") or "gathering_info",
            qualified=bool(data.get("qualified")),
            score=data.get("score") if data.get("score") in ("hot", "warm", "cold", "unscored") else "unscored",
            qualification_updates=updates,
            lead_name=str(data.get("lead_name") or "")[:120],
            lead_email=str(data.get("lead_email") or "")[:254],
            lead_phone=str(data.get("lead_phone") or "")[:32],
            service_interest=str(data.get("service_interest") or "")[:120],
            location=str(data.get("location") or "")[:160],
            selected_slot_index=_as_index(data.get("selected_slot_index")),
            needs_human=bool(data.get("needs_human")),
            unanswered_question=str(data.get("unanswered_question") or "")[:300],
            provider=self.name,
        )


def _as_index(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1
