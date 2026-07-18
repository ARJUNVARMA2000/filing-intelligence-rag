from functools import lru_cache

from .config import Settings, get_settings
from .llm_client import ChatClient
from .openai_client import OpenAIClient
from .openrouter_client import OpenRouterClient
from .vertex_client import VertexAIClient


@lru_cache
def get_app_settings() -> Settings:
    return get_settings()


@lru_cache
def get_openai_client() -> ChatClient:
    settings = get_app_settings()
    if settings.llm_provider == "vertexai":
        return VertexAIClient(
            project=settings.gcp_project,
            location=settings.vertex_location,
            chat_model=settings.vertex_chat_model,
            max_output_tokens=settings.llm_max_output_tokens,
        )
    return OpenAIClient(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        chat_model=settings.openai_chat_model,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        max_output_tokens=settings.llm_max_output_tokens,
    )


@lru_cache(maxsize=16)
def _get_openrouter_client(model: str | None) -> OpenRouterClient:
    """Get an OpenRouter client for multi-model evaluation."""
    settings = get_app_settings()
    return OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        default_model=model or "openai/gpt-4o",
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        max_output_tokens=settings.llm_max_output_tokens,
    )


def get_openrouter_client(model: str | None = None) -> OpenRouterClient:
    return _get_openrouter_client(model)
