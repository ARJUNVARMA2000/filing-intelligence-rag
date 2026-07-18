from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ProviderError(RuntimeError):
    """Normalized failure raised by an upstream model provider."""

    def __init__(self, provider: str, operation: str) -> None:
        super().__init__(f"{provider} failed during {operation}")
        self.provider = provider
        self.operation = operation


@dataclass(frozen=True)
class ChatResult:
    """Provider-neutral completion result with normalized usage metadata."""

    answer: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    model: str = ""


class ChatClient(Protocol):
    """Compatibility protocol used by the existing RAG and parser services."""

    def chat(self, system_prompt: str, user_message: str) -> str: ...
