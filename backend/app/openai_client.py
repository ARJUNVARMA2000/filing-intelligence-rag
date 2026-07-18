from __future__ import annotations

from openai import OpenAI

from .llm_client import ProviderError


class OpenAIClient:
    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        chat_model: str = "gpt-4.1-mini",
        timeout: float = 60.0,
        max_retries: int = 2,
        max_output_tokens: int = 2048,
    ) -> None:
        client_kwargs = {
            "api_key": api_key,
            "timeout": timeout,
            "max_retries": max_retries,
        }
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = OpenAI(**client_kwargs)
        self.chat_model = chat_model
        self.max_output_tokens = max_output_tokens

    def chat(self, system_prompt: str, user_message: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self.chat_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,
                max_completion_tokens=self.max_output_tokens,
            )
        except Exception as exc:
            raise ProviderError("openai", "chat completion") from exc
        return response.choices[0].message.content or ""
