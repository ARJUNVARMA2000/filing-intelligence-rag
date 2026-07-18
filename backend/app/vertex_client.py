from __future__ import annotations

from .llm_client import ProviderError


class VertexAIClient:
    def __init__(
        self,
        *,
        project: str,
        location: str,
        chat_model: str,
        max_output_tokens: int = 2048,
    ) -> None:
        from google import genai
        from google.genai import types

        self._client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            http_options=types.HttpOptions(api_version="v1"),
        )
        self._types = types
        self.chat_model = chat_model
        self.max_output_tokens = max_output_tokens

    def chat(self, system_prompt: str, user_message: str) -> str:
        try:
            response = self._client.models.generate_content(
                model=self.chat_model,
                contents=user_message,
                config=self._types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.1,
                    max_output_tokens=self.max_output_tokens,
                ),
            )
        except Exception as exc:
            raise ProviderError("vertexai", "chat completion") from exc
        return response.text or ""
