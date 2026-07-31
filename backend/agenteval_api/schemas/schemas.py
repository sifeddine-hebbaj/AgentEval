"""Pydantic request/response schemas for the REST API (SRS section 7)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# -- Auth ---------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ApiKeyCreateRequest(BaseModel):
    project_id: UUID
    name: str = "default"


class ApiKeyCreateResponse(BaseModel):
    id: UUID
    name: str
    plaintext_key: str  # shown ONCE at creation only
    key_prefix: str


# -- Projects -------------------------------------------------------------------

class ProjectCreateRequest(BaseModel):
    org_id: UUID
    name: str
    slug: str


class ProjectResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    slug: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# -- Traces -----------------------------------------------------------------

class SpanIn(BaseModel):
    id: UUID | None = None
    parent_span_id: UUID | None = None
    span_type: str = "custom"
    name: str = ""
    input: Any = None
    output: Any = None
    model_name: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    status: str = "ok"
    error_message: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class TraceIn(BaseModel):
    id: UUID | None = None
    environment: str = "development"
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "ok"
    spans: list[SpanIn] = Field(default_factory=list)
    started_at: datetime | None = None
    ended_at: datetime | None = None


class TraceOut(BaseModel):
    id: UUID
    environment: str
    status: str
    total_tokens: int
    total_cost: float
    duration_ms: int | None
    started_at: datetime
    ended_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class TraceDetailOut(TraceOut):
    spans: list[SpanIn]
    metadata: dict[str, Any]


# -- Datasets ---------------------------------------------------------------

class DatasetCreateRequest(BaseModel):
    project_id: UUID
    name: str
    description: str = ""


class TestCaseIn(BaseModel):
    input: Any
    expected_output: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class DatasetVersionCreateRequest(BaseModel):
    test_cases: list[TestCaseIn]
    created_by: str = ""


class DatasetResponse(BaseModel):
    id: UUID
    name: str
    description: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DatasetVersionResponse(BaseModel):
    id: UUID
    dataset_id: UUID
    version_number: int
    test_case_count: int
    created_at: datetime


# -- Scorers ------------------------------------------------------------------

class ScorerCreateRequest(BaseModel):
    project_id: UUID
    name: str
    scorer_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    output_type: str = "numeric"


class ScorerVersionResponse(BaseModel):
    id: UUID
    scorer_id: UUID
    version_number: int
    config: dict[str, Any]
    output_type: str


class EvalSuiteCreateRequest(BaseModel):
    project_id: UUID
    name: str
    scorer_version_ids: list[UUID]
    weights: dict[str, float] = Field(default_factory=dict)  # scorer_version_id(str) -> weight
    critical_scorer_version_ids: list[UUID] = Field(default_factory=list)


class EvalSuiteResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str


# -- Eval Runs ----------------------------------------------------------------

class EvalRunCreateRequest(BaseModel):
    dataset_version_id: UUID
    eval_suite_id: UUID
    trigger_source: str = "api"
    git_sha: str | None = None
    baseline_run_id: UUID | None = None
    precomputed_outputs: dict[str, Any] | None = None  # test_case_id(str) -> output


class EvalRunResponse(BaseModel):
    id: UUID
    status: str
    total_test_cases: int
    completed_test_cases: int
    aggregate_metrics: dict[str, Any]
    started_at: datetime
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ScoreOut(BaseModel):
    scorer_name: str
    numeric_value: float | None
    boolean_value: bool | None
    category_value: str | None
    rationale: str | None
    error: str | None


class EvalResultOut(BaseModel):
    id: UUID
    test_case_id: UUID
    actual_output: Any
    status: str
    latency_ms: int | None
    scores: list[ScoreOut]


class RegressedCase(BaseModel):
    test_case_id: str
    scorer: str
    baseline_score: float | None
    new_score: float | None


class SignificanceEntry(BaseModel):
    mean_delta: float
    ci_low: float
    ci_high: float
    significant: bool
    p_value_approx: float


class EvalRunDiffResponse(BaseModel):
    run_id: UUID
    baseline_id: UUID
    aggregate_delta: dict[str, float]
    regressed_cases: list[RegressedCase]
    improved_cases: list[RegressedCase]
    significance: dict[str, SignificanceEntry]


class ErrorResponse(BaseModel):
    """RFC 7807 Problem Details."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None
