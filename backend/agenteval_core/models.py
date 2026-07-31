"""Pure domain models for AgentEval. No I/O, no framework dependency."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class OutputType(str, Enum):
    NUMERIC = "numeric"
    BOOLEAN = "boolean"
    CATEGORICAL = "categorical"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class SpanType(str, Enum):
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    RETRIEVAL = "retrieval"
    CUSTOM = "custom"


class ScoreResult(BaseModel):
    """The result produced by a single scorer for a single test case/trace."""

    numeric_value: Optional[float] = None
    boolean_value: Optional[bool] = None
    category_value: Optional[str] = None
    rationale: Optional[str] = None
    error: Optional[str] = None

    def passed(self, threshold: float = 0.5) -> bool:
        """Best-effort pass/fail interpretation across output types."""
        if self.error is not None:
            return False
        if self.boolean_value is not None:
            return self.boolean_value
        if self.numeric_value is not None:
            return self.numeric_value >= threshold
        if self.category_value is not None:
            return self.category_value.lower() in {"pass", "true", "correct", "yes"}
        return False


class TestCase(BaseModel):
    id: str = Field(default_factory=_uuid)
    input: Any
    expected_output: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class Dataset(BaseModel):
    id: str = Field(default_factory=_uuid)
    name: str
    version_number: int = 1
    test_cases: list[TestCase] = Field(default_factory=list)

    @classmethod
    def from_jsonl(cls, path: str, name: str | None = None) -> "Dataset":
        import json

        test_cases: list[TestCase] = []
        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_no}: invalid JSON ({exc})") from exc
                if "input" not in row:
                    raise ValueError(f"{path}:{line_no}: missing required field 'input'")
                test_cases.append(
                    TestCase(
                        input=row["input"],
                        expected_output=row.get("expected_output"),
                        metadata=row.get("metadata", {}),
                        tags=row.get("tags", []),
                    )
                )
        return cls(name=name or path, test_cases=test_cases)

    @classmethod
    def from_csv(cls, path: str, name: str | None = None) -> "Dataset":
        import csv

        test_cases: list[TestCase] = []
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or "input" not in reader.fieldnames:
                raise ValueError(f"{path}: CSV must have an 'input' column")
            for line_no, row in enumerate(reader, start=2):
                tags = [t.strip() for t in row.get("tags", "").split(",") if t.strip()]
                test_cases.append(
                    TestCase(
                        input=row["input"],
                        expected_output=row.get("expected_output"),
                        tags=tags,
                    )
                )
        return cls(name=name or path, test_cases=test_cases)


class EvalResult(BaseModel):
    id: str = Field(default_factory=_uuid)
    run_id: str
    test_case_id: str
    actual_output: Any = None
    status: str = "ok"  # ok | error
    error_message: Optional[str] = None
    latency_ms: Optional[int] = None
    scores: dict[str, ScoreResult] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class EvalRunSummary(BaseModel):
    id: str = Field(default_factory=_uuid)
    dataset_id: str
    status: RunStatus = RunStatus.PENDING
    total_test_cases: int = 0
    completed_test_cases: int = 0
    aggregate_metrics: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=_now)
    completed_at: Optional[datetime] = None


class Span(BaseModel):
    id: str = Field(default_factory=_uuid)
    trace_id: str
    parent_span_id: Optional[str] = None
    span_type: SpanType = SpanType.CUSTOM
    name: str = ""
    input: Any = None
    output: Any = None
    model_name: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    status: str = "ok"
    error_message: Optional[str] = None
    started_at: datetime = Field(default_factory=_now)
    ended_at: Optional[datetime] = None


class Trace(BaseModel):
    id: str = Field(default_factory=_uuid)
    project_id: Optional[str] = None
    environment: str = "development"
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "ok"
    spans: list[Span] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_now)
    ended_at: Optional[datetime] = None

    @property
    def total_tokens(self) -> int:
        return sum(s.prompt_tokens + s.completion_tokens for s in self.spans)

    @property
    def total_cost(self) -> float:
        return sum(s.cost for s in self.spans)

    @property
    def duration_ms(self) -> Optional[int]:
        if self.ended_at is None:
            return None
        return int((self.ended_at - self.started_at).total_seconds() * 1000)
