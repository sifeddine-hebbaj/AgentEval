"""Built-in deterministic scorers. No network calls, no external state."""
from __future__ import annotations

import json
import re
from typing import Any

from agenteval_core.models import OutputType, ScoreResult
from agenteval_core.scorers.base import BaseScorer, registry


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


class ExactMatchScorer(BaseScorer):
    name = "exact_match"
    output_type = OutputType.BOOLEAN

    def __init__(self, case_sensitive: bool = True) -> None:
        self.case_sensitive = case_sensitive

    def _score(self, input, output, expected, metadata) -> ScoreResult:
        a, b = _to_str(output).strip(), _to_str(expected).strip()
        if not self.case_sensitive:
            a, b = a.lower(), b.lower()
        match = a == b
        return ScoreResult(boolean_value=match, rationale="exact string match" if match else "strings differ")


class ContainsScorer(BaseScorer):
    name = "contains"
    output_type = OutputType.BOOLEAN

    def __init__(self, case_sensitive: bool = False) -> None:
        self.case_sensitive = case_sensitive

    def _score(self, input, output, expected, metadata) -> ScoreResult:
        haystack, needle = _to_str(output), _to_str(expected)
        if not self.case_sensitive:
            haystack, needle = haystack.lower(), needle.lower()
        found = needle != "" and needle in haystack
        return ScoreResult(boolean_value=found)


class RegexMatchScorer(BaseScorer):
    name = "regex_match"
    output_type = OutputType.BOOLEAN

    def __init__(self, pattern: str | None = None) -> None:
        self.pattern = pattern

    def _score(self, input, output, expected, metadata) -> ScoreResult:
        pattern = self.pattern or _to_str(expected)
        if not pattern:
            return ScoreResult(error="regex_match: no pattern provided (set 'pattern' or 'expected_output')")
        matched = re.search(pattern, _to_str(output)) is not None
        return ScoreResult(boolean_value=matched)


class JsonSchemaValidScorer(BaseScorer):
    name = "json_schema_valid"
    output_type = OutputType.BOOLEAN

    def __init__(self, schema: dict | None = None) -> None:
        self.schema = schema

    def _score(self, input, output, expected, metadata) -> ScoreResult:
        import jsonschema

        schema = self.schema or (expected if isinstance(expected, dict) else None)
        if schema is None:
            return ScoreResult(error="json_schema_valid: no schema provided")
        parsed = output if not isinstance(output, str) else json.loads(output)
        try:
            jsonschema.validate(parsed, schema)
        except jsonschema.ValidationError as exc:
            return ScoreResult(boolean_value=False, rationale=str(exc.message))
        return ScoreResult(boolean_value=True)


class LevenshteinSimilarityScorer(BaseScorer):
    name = "levenshtein_similarity"
    output_type = OutputType.NUMERIC

    def __init__(self, threshold: float = 0.8) -> None:
        self.threshold = threshold

    @staticmethod
    def _distance(a: str, b: str) -> int:
        if a == b:
            return 0
        if len(a) == 0:
            return len(b)
        if len(b) == 0:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, start=1):
            curr = [i] + [0] * len(b)
            for j, cb in enumerate(b, start=1):
                cost = 0 if ca == cb else 1
                curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
            prev = curr
        return prev[-1]

    def _score(self, input, output, expected, metadata) -> ScoreResult:
        a, b = _to_str(output), _to_str(expected)
        max_len = max(len(a), len(b), 1)
        dist = self._distance(a, b)
        similarity = 1.0 - (dist / max_len)
        return ScoreResult(
            numeric_value=round(similarity, 4),
            rationale=f"levenshtein similarity={similarity:.4f} (threshold={self.threshold})",
        )


class LatencyThresholdScorer(BaseScorer):
    name = "latency_threshold"
    output_type = OutputType.BOOLEAN

    def __init__(self, max_ms: int = 5000) -> None:
        self.max_ms = max_ms

    def _score(self, input, output, expected, metadata) -> ScoreResult:
        latency = metadata.get("latency_ms")
        if latency is None:
            return ScoreResult(error="latency_threshold: metadata['latency_ms'] not provided")
        return ScoreResult(boolean_value=latency <= self.max_ms, rationale=f"{latency}ms vs {self.max_ms}ms budget")


class CostThresholdScorer(BaseScorer):
    name = "cost_threshold"
    output_type = OutputType.BOOLEAN

    def __init__(self, max_usd: float = 0.10) -> None:
        self.max_usd = max_usd

    def _score(self, input, output, expected, metadata) -> ScoreResult:
        cost = metadata.get("cost_usd")
        if cost is None:
            return ScoreResult(error="cost_threshold: metadata['cost_usd'] not provided")
        return ScoreResult(boolean_value=cost <= self.max_usd, rationale=f"${cost:.4f} vs ${self.max_usd:.4f} budget")


registry.register("exact_match", ExactMatchScorer)
registry.register("contains", ContainsScorer)
registry.register("regex_match", RegexMatchScorer)
registry.register("json_schema_valid", JsonSchemaValidScorer)
registry.register("levenshtein_similarity", LevenshteinSimilarityScorer)
registry.register("latency_threshold", LatencyThresholdScorer)
registry.register("cost_threshold", CostThresholdScorer)
