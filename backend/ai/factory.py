import os

from .provider import AIProvider

_provider_instance: AIProvider | None = None


def get_provider() -> AIProvider:
    global _provider_instance
    if _provider_instance is None:
        provider_name = os.getenv("AI_PROVIDER", "openai").lower()
        if provider_name == "openai":
            from .providers.openai_provider import OpenAIProvider
            _provider_instance = OpenAIProvider()
        elif provider_name == "custom":
            from .providers.openai_provider import OpenAIProvider
            _provider_instance = OpenAIProvider(
                base_url=os.getenv("AI_BASE_URL"),
                model=os.getenv("AI_MODEL", "gpt-4o"),
            )
        else:
            raise ValueError(f"Unknown AI_PROVIDER: {provider_name}")
    return _provider_instance
