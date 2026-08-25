"""
Provider abstraction.

Swapping the model means adding one class here and one env var — nothing else
in the codebase talks to a model directly.
"""

from dataclasses import dataclass, field


@dataclass
class AITurn:
    """Normalised result of one assistant turn, whatever produced it."""
    reply: str
    intent: str = "gathering_info"
    qualified: bool = False
    score: str = "unscored"
    qualification_updates: dict = field(default_factory=dict)
    lead_name: str = ""
    lead_email: str = ""
    lead_phone: str = ""
    service_interest: str = ""
    location: str = ""
    selected_slot_index: int = -1
    needs_human: bool = False
    unanswered_question: str = ""
    # Conversation bookkeeping the engine stores on the outgoing message so the
    # next turn knows what was asked and whether times were offered.
    pending_key: str = ""
    offered_slots: bool = False
    provider: str = "rules"
    error: str = ""


class AIProvider:
    name = "base"

    def available(self) -> bool:
        raise NotImplementedError

    def generate(self, ctx, directive="reply", incoming=None) -> AITurn:
        raise NotImplementedError


def get_provider():
    """Resolve the configured provider, always with a working fallback.

    The rules engine is not a stub: it runs the full qualification and booking
    flow, so the product works end-to-end with zero credentials (which is what
    makes demo mode demoable).
    """
    from .. import config
    from .rules_provider import RulesProvider

    if config.AI_PROVIDER == "rules":
        return RulesProvider()

    if config.AI_PROVIDER in ("auto", "anthropic"):
        from .anthropic_provider import AnthropicProvider
        provider = AnthropicProvider()
        if provider.available():
            return provider
        if config.AI_PROVIDER == "anthropic":
            print("[ai] ANTHROPIC_API_KEY or the anthropic SDK is missing — "
                  "falling back to the built-in rules engine.")
    return RulesProvider()
