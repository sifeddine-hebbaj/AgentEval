"""SQLAlchemy ORM models -- the storage schema (SRS section 6).

Deliberately kept separate from agenteval_core's pure domain models:
this file describes *how data is persisted*, agenteval_core describes
*what the evaluation engine operates on*. A thin mapping layer
(agenteval_api/repositories/postgres_repo.py) translates between them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import ARRAY, Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agenteval_api.db import Base


def _uuid_col():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = _uuid_col()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    projects: Mapped[list["Project"]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_col()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UserOrgRole(Base):
    __tablename__ = "user_org_roles"
    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # owner|admin|member|viewer

    __table_args__ = (UniqueConstraint("user_id", "org_id", name="uq_user_org"),)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = _uuid_col()
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    retention_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    organization: Mapped["Organization"] = relationship(back_populates="projects")


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), default="default")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    versions: Mapped[list["DatasetVersion"]] = relationship(back_populates="dataset", order_by="DatasetVersion.version_number")


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    id: Mapped[uuid.UUID] = _uuid_col()
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    dataset: Mapped["Dataset"] = relationship(back_populates="versions")
    test_cases: Mapped[list["TestCaseORM"]] = relationship(back_populates="dataset_version")

    __table_args__ = (UniqueConstraint("dataset_id", "version_number", name="uq_dataset_version"),)


class TestCaseORM(Base):
    __tablename__ = "test_cases"
    id: Mapped[uuid.UUID] = _uuid_col()
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id"), nullable=False, index=True
    )
    input: Mapped[dict] = mapped_column(JSON, nullable=False)
    expected_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    dataset_version: Mapped["DatasetVersion"] = relationship(back_populates="test_cases")


class Trace(Base):
    __tablename__ = "traces"
    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(50), default="development")
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    spans: Mapped[list["Span"]] = relationship(back_populates="trace")


class Span(Base):
    __tablename__ = "spans"
    id: Mapped[uuid.UUID] = _uuid_col()
    trace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("traces.id"), nullable=False, index=True)
    parent_span_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("spans.id"), nullable=True, index=True)
    span_type: Mapped[str] = mapped_column(String(30), default="custom")
    name: Mapped[str] = mapped_column(String(200), default="")
    input_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    trace: Mapped["Trace"] = relationship(back_populates="spans")


class Scorer(Base):
    __tablename__ = "scorers"
    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scorer_type: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    versions: Mapped[list["ScorerVersion"]] = relationship(back_populates="scorer", order_by="ScorerVersion.version_number")


class ScorerVersion(Base):
    __tablename__ = "scorer_versions"
    id: Mapped[uuid.UUID] = _uuid_col()
    scorer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("scorers.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    output_type: Mapped[str] = mapped_column(String(20), default="numeric")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    scorer: Mapped["Scorer"] = relationship(back_populates="versions")

    __table_args__ = (UniqueConstraint("scorer_id", "version_number", name="uq_scorer_version"),)


class EvalSuite(Base):
    __tablename__ = "eval_suites"
    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    scorer_links: Mapped[list["EvalSuiteScorer"]] = relationship(back_populates="eval_suite")


class EvalSuiteScorer(Base):
    __tablename__ = "eval_suite_scorers"
    id: Mapped[uuid.UUID] = _uuid_col()
    eval_suite_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("eval_suites.id"), nullable=False, index=True)
    scorer_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("scorer_versions.id"), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)

    eval_suite: Mapped["EvalSuite"] = relationship(back_populates="scorer_links")
    scorer_version: Mapped["ScorerVersion"] = relationship()


class EvalRun(Base):
    __tablename__ = "eval_runs"
    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("dataset_versions.id"), nullable=False)
    eval_suite_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("eval_suites.id"), nullable=False)
    baseline_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("eval_runs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    trigger_source: Mapped[str] = mapped_column(String(50), default="api")
    git_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_test_cases: Mapped[int] = mapped_column(Integer, default=0)
    completed_test_cases: Mapped[int] = mapped_column(Integer, default=0)
    aggregate_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    results: Mapped[list["EvalResult"]] = relationship(back_populates="eval_run")


class EvalResult(Base):
    __tablename__ = "eval_results"
    id: Mapped[uuid.UUID] = _uuid_col()
    eval_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("eval_runs.id"), nullable=False, index=True)
    test_case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("test_cases.id"), nullable=False, index=True)
    actual_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    eval_run: Mapped["EvalRun"] = relationship(back_populates="results")
    scores: Mapped[list["Score"]] = relationship(back_populates="eval_result")


class Score(Base):
    __tablename__ = "scores"
    id: Mapped[uuid.UUID] = _uuid_col()
    eval_result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("eval_results.id"), nullable=False, index=True)
    scorer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    numeric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    boolean_value: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    category_value: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    eval_result: Mapped["EvalResult"] = relationship(back_populates="scores")

    __table_args__ = (UniqueConstraint("eval_result_id", "scorer_name", name="uq_score_per_scorer"),)


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    scorer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    channel: Mapped[str] = mapped_column(String(50), default="webhook")
    channel_config: Mapped[dict] = mapped_column(JSON, default=dict)


class Baseline(Base):
    """Tracks which EvalRun is 'the baseline' for a given (dataset, suite)
    pair (FR-EVAL-4). Deliberately keyed on dataset_id (not
    dataset_version_id) since the baseline should persist as the dataset
    evolves through versions.
    """
    __tablename__ = "baselines"
    id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=False)
    eval_suite_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("eval_suites.id"), nullable=False)
    eval_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("eval_runs.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (UniqueConstraint("project_id", "dataset_id", "eval_suite_id", name="uq_baseline_scope"),)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = _uuid_col()
    actor: Mapped[str] = mapped_column(String(320), default="anonymous")
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
