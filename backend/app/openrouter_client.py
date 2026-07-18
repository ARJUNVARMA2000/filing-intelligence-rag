"""
OpenRouter client for multi-model LLM access.

OpenRouter provides a unified API (OpenAI-compatible) to access multiple LLM providers.
"""

from __future__ import annotations

from openai import OpenAI

from .config import OPENROUTER_BASE_URL
from .llm_client import ChatResult, ProviderError
from .models_registry import estimate_cost


class OpenRouterClient:
    """Client for accessing LLMs via OpenRouter."""

    def __init__(
        self,
        api_key: str,
        base_url: str = OPENROUTER_BASE_URL,
        default_model: str = "openai/gpt-4o",
        timeout: float = 60.0,
        max_retries: int = 2,
        max_output_tokens: int = 2048,
    ) -> None:
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={
                "HTTP-Referer": "https://github.com/aml-eval",  # Required by OpenRouter
                "X-Title": "AML Eval System",  # Optional, for OpenRouter dashboard
            },
            timeout=timeout,
            max_retries=max_retries,
        )
        self.default_model = default_model
        self.max_output_tokens = max_output_tokens

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        model: str | None = None,
        temperature: float = 0.1,
    ) -> ChatResult:
        """
        Send a chat completion request and return the result with usage metrics.

        Args:
            system_prompt: System message for the conversation
            user_message: User's message/question
            model: OpenRouter model ID (e.g., "anthropic/claude-sonnet-4-20250514")
            temperature: Sampling temperature (default 0.1 for consistency)

        Returns:
            ChatResult with answer, token counts, and cost
        """
        model_to_use = model or self.default_model

        try:
            response = self._client.chat.completions.create(
                model=model_to_use,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                max_completion_tokens=self.max_output_tokens,
            )
        except Exception as exc:
            raise ProviderError("openrouter", "chat completion") from exc

        # Extract usage information
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        total_tokens = usage.total_tokens if usage else 0

        # Try to get cost from OpenRouter response headers or estimate
        # OpenRouter includes cost in the response when available
        cost = self._extract_cost(response, model_to_use, input_tokens, output_tokens)

        answer = response.choices[0].message.content or ""

        return ChatResult(
            answer=answer,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost=cost,
            model=model_to_use,
        )

    def _extract_cost(
        self,
        response,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Extract cost from OpenRouter response or estimate it."""
        # OpenRouter may include cost in response metadata
        # Check if the response has cost information in model_extra
        if (
            hasattr(response, "model_extra")
            and response.model_extra
            and "cost" in response.model_extra
        ):
            return float(response.model_extra["cost"])

        # Fall back to estimation based on token counts
        return estimate_cost(model_id, input_tokens, output_tokens)

    def simple_chat(self, prompt: str, model: str | None = None) -> str:
        """Simple chat interface that just returns the answer string."""
        result = self.chat(
            system_prompt="You are a helpful assistant.",
            user_message=prompt,
            model=model,
        )
        return result.answer
