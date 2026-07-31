"""agenteval_core: framework-agnostic evaluation engine.

This package has zero dependency on web frameworks, databases, or
message queues. It defines the domain model and the evaluation engine
that both the server (via a Postgres-backed repository) and the local
SDK/CLI (via a SQLite-backed repository) reuse without duplication.
"""
from agenteval_core.engine import EvalEngine
from agenteval_core.models import (
    Dataset,
    EvalResult,
    EvalRunSummary,
    OutputType,
    RunStatus,
    ScoreResult,
    Span,
    SpanType,
    TestCase,
    Trace,
)
from agenteval_core.repository import EvalResultRepository, InMemoryEvalResultRepository

__all__ = [
    "Dataset",
    "EvalEngine",
    "EvalResult",
    "EvalResultRepository",
    "EvalRunSummary",
    "InMemoryEvalResultRepository",
    "OutputType",
    "RunStatus",
    "ScoreResult",
    "Span",
    "SpanType",
    "TestCase",
    "Trace",
]

__version__ = "0.1.0"
