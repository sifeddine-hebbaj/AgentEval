"""LLM-as-judge scorer.

Design constraints (see SRS section 9.3):
  * Judge output MUST be structured (JSON), never parsed from free text.
  * A malformed/unparseable judge response is a scorer error, not a crash.
  * The judge model is pluggable via the JudgeModelAdapter protocol so the
    project is never locked to one vendor (SRS NFR-PORT-2).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from agenteval_core.models import OutputType, ScoreResult
from agenteval_core.scorers.base import BaseScorer, registry

DEFAULT_RUBRIC = """You are an impartial evaluator. Score the AI agent's response.

Input: {input}
Expected/reference (if any): {expected}
Agent's actual response: {output}

Score from 0.0 (very poor) to 1.0 (excellent) based on correctness and helpfulness.
Respond with ONLY a JSON object of the exact form:
{{"score": <float between 0 and 1>, "rationale": "<one sentence>"}}
No other text."""


class JudgeModelAdapter(Protocol):
    """Implemented per-provider (OpenAI, Anthropic, Ollama, ...).

    Must return the raw text content of the model's structured JSON reply.
    """

    def complete_json(self, prompt: str) -> str: ...


class _ScoreCache(Protocol):
    def get(self, key: str) -> ScoreResult | None: ...
    def set(self, key: str, value: ScoreResult) -> None: ...


class InMemoryScoreCache:
    """Default cache; swap for a Redis-backed one server-side (see
    agenteval_api) without changing LLMJudgeScorer's logic at all.
    """

    def __init__(self) -> None:
        self._store: dict[str, ScoreResult] = {}

    def get(self, key: str) -> ScoreResult | None:
        return self._store.get(key)

    def set(self, key: str, value: ScoreResult) -> None:
        self._store[key] = value


class LLMJudgeScorer(BaseScorer):
    name = "llm_judge"
    output_type = OutputType.NUMERIC

    def __init__(
        self,
        adapter: JudgeModelAdapter,
        rubric_template: str = DEFAULT_RUBRIC,
        cache: _ScoreCache | None = None,
        scorer_version_id: str = "default",
    ) -> None:
        self.adapter = adapter
        self.rubric_template = rubric_template
        self.cache = cache or InMemoryScoreCache()
        self.scorer_version_id = scorer_version_id

    def _cache_key(self, input: Any, output: Any) -> str:
        raw = json.dumps({"i": input, "o": output}, sort_keys=True, default=str)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"{self.scorer_version_id}:{digest}"

    def _score(self, input, output, expected, metadata) -> ScoreResult:
        key = self._cache_key(input, output)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        prompt = self.rubric_template.format(
            input=json.dumps(input, default=str),
            output=json.dumps(output, default=str),
            expected=json.dumps(expected, default=str),
        )
        raw = self.adapter.complete_json(prompt)

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return ScoreResult(error=f"llm_judge: judge did not return valid JSON: {raw[:200]!r}")

        score = parsed.get("score")
        if not isinstance(score, (int, float)):
            return ScoreResult(error=f"llm_judge: response missing numeric 'score' field: {parsed}")
        if not (0.0 <= float(score) <= 1.0):
            return ScoreResult(error=f"llm_judge: score {score} out of [0,1] range")

        result = ScoreResult(numeric_value=float(score), rationale=parsed.get("rationale"))
        self.cache.set(key, result)
        return result


# --- Reference provider adapters -------------------------------------------------

class OpenAIJudgeAdapter:
    """Adapter for OpenAI-compatible chat completion APIs."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", base_url: str | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    def complete_json(self, prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return response.choices[0].message.content or "{}"


class AnthropicJudgeAdapter:
    """Adapter for Anthropic's Messages API, using a tool-call to force
    structured JSON output rather than free-text parsing.
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-5") -> None:
        self.api_key = api_key
        self.model = model

    def complete_json(self, prompt: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        tool = {
            "name": "submit_score",
            "description": "Submit the evaluation score and rationale.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "score": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale": {"type": "string"},
                },
                "required": ["score", "rationale"],
            },
        }
        response = client.messages.create(
            model=self.model,
            max_tokens=256,
            tools=[tool],
            tool_choice={"type": "tool", "name": "submit_score"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if block.type == "tool_use":
                return json.dumps(block.input)
        return "{}"


class OllamaJudgeAdapter:
    """Adapter for a local Ollama server -- keeps a fully offline judge
    path available per SRS NFR-PORT-2.
    """

    def __init__(self, model: str = "llama3.1", base_url: str = "http://localhost:11434") -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")

    def complete_json(self, prompt: str) -> str:
        import httpx

        resp = httpx.post(
            f"{self.base_url}/api/generate",
            json={"model": self.model, "prompt": prompt, "format": "json", "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("response", "{}")


registry.register("llm_judge", LLMJudgeScorer)
