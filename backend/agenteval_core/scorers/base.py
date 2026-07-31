"""Scorer protocol + registry.

Contract: score() must NEVER raise. Any failure must be captured and
returned as ScoreResult(error=...). The engine and workers rely on this
contract to isolate a single scorer/test-case failure from crashing an
entire eval run (see SRS NFR-AVAIL-3).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from agenteval_core.models import OutputType, ScoreResult


@runtime_checkable
class Scorer(Protocol):
    name: str
    output_type: OutputType

    def score(self, input: Any, output: Any, expected: Any, metadata: dict) -> ScoreResult: ...


class BaseScorer:
    """Convenience base class that enforces the never-raise contract."""

    name: str = "base"
    output_type: OutputType = OutputType.NUMERIC

    def _score(self, input: Any, output: Any, expected: Any, metadata: dict) -> ScoreResult:
        raise NotImplementedError

    def score(self, input: Any, output: Any, expected: Any, metadata: dict) -> ScoreResult:
        try:
            return self._score(input, output, expected, metadata or {})
        except Exception as exc:
            return ScoreResult(error=f"{type(exc).__name__}: {exc}")


class ScorerRegistry:
    """String-name -> Scorer lookup, used by config-driven Eval Suites
    (agenteval.yaml, API-registered suites) to resolve built-in scorers
    without hardcoding imports everywhere.
    """

    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., Scorer]] = {}

    def register(self, name: str, factory: Callable[..., Scorer]) -> None:
        self._factories[name] = factory

    def create(self, name: str, **kwargs: Any) -> Scorer:
        if name not in self._factories:
            raise KeyError(
                f"Unknown scorer '{name}'. Registered scorers: {sorted(self._factories)}"
            )
        return self._factories[name](**kwargs)

    def names(self) -> list[str]:
        return sorted(self._factories)


registry = ScorerRegistry()
