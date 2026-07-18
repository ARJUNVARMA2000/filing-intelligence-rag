"""
Evaluation judge module using Claude Opus to assess answer correctness.

This module provides functionality to compare LLM-generated answers against
expected answers and determine if they are semantically correct.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..dependencies import get_openrouter_client
from ..models_registry import JUDGE_MODEL
from ..openrouter_client import OpenRouterClient

JUDGE_SYSTEM_PROMPT = """You are an expert evaluator assessing whether an AI-generated answer correctly addresses a question based on an expected answer.

Your task is to determine if the AI's answer is CORRECT or INCORRECT.

Guidelines for evaluation:
1. The AI answer does not need to be word-for-word identical to the expected answer
2. The AI answer should contain the key facts, numbers, and conclusions from the expected answer
3. Minor differences in phrasing, formatting, or additional context are acceptable if the core answer is correct
4. If the AI answer contains the correct information but also includes incorrect information, mark it as INCORRECT
5. If the AI answer is a partial match (missing key information), mark it as INCORRECT
6. Numbers must be accurate (small rounding differences are acceptable)

Respond with ONLY one word: CORRECT or INCORRECT

Do not provide any explanation or additional text."""


JUDGE_USER_TEMPLATE = """Question: {question}

Expected Answer: {expected_answer}

AI-Generated Answer: {actual_answer}

Is the AI-generated answer correct?"""


@dataclass
class JudgmentResult:
    """Result from the judge evaluation."""

    is_correct: bool
    question: str
    expected_answer: str
    actual_answer: str
    input_tokens: int
    output_tokens: int
    cost: float


class EvalJudge:
    """Judge for evaluating answer correctness using Claude Opus."""

    def __init__(self, openrouter_client: OpenRouterClient | None = None) -> None:
        self._client = openrouter_client or get_openrouter_client(JUDGE_MODEL)
        self._model = JUDGE_MODEL

    def judge_answer(
        self,
        question: str,
        expected_answer: str,
        actual_answer: str,
    ) -> JudgmentResult:
        """
        Judge whether the actual answer correctly addresses the question.

        Args:
            question: The original question
            expected_answer: The expected/ground truth answer
            actual_answer: The AI-generated answer to evaluate

        Returns:
            JudgmentResult with correctness determination and usage info
        """
        user_message = JUDGE_USER_TEMPLATE.format(
            question=question,
            expected_answer=expected_answer,
            actual_answer=actual_answer,
        )

        result = self._client.chat(
            system_prompt=JUDGE_SYSTEM_PROMPT,
            user_message=user_message,
            model=self._model,
            temperature=0.0,  # Deterministic for consistency
        )

        # Parse the response - should be "CORRECT" or "INCORRECT"
        response_text = result.answer.strip().upper()
        is_correct = response_text == "CORRECT"

        return JudgmentResult(
            is_correct=is_correct,
            question=question,
            expected_answer=expected_answer,
            actual_answer=actual_answer,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost=result.cost,
        )


def get_eval_judge() -> EvalJudge:
    """Get an instance of the evaluation judge."""
    return EvalJudge()
