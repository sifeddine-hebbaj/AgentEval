"""Celery tasks: one job per test case (SRS Task 3.1's key design
decision -- never one giant job for a whole run, so partial failures
are isolated and workers scale horizontally, NFR-SCALE-1/NFR-AVAIL-3).
"""
from __future__ import annotations

import uuid

from celery import chord
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from agenteval_api.celery_app import celery_app
from agenteval_api.config import settings
from agenteval_api.models.orm import (
    EvalSuiteScorer,
    ScorerVersion,
    TestCaseORM,
)
from agenteval_api.repositories.postgres_repo import PostgresEvalResultRepository, _sync_url
from agenteval_core.engine import EvalEngine
from agenteval_core.models import RunStatus, TestCase
from agenteval_core.scorers.base import Scorer
from agenteval_core.scorers import registry as core_registry
from agenteval_core.scorers.llm_judge import (
    AnthropicJudgeAdapter,
    LLMJudgeScorer,
    OllamaJudgeAdapter,
    OpenAIJudgeAdapter,
)

_engine = create_engine(_sync_url(settings.database_url), pool_pre_ping=True)
_Session: sessionmaker[Session] = sessionmaker(bind=_engine)


def _build_judge_adapter():
    if settings.judge_provider == "openai":
        return OpenAIJudgeAdapter(api_key=settings.openai_api_key or "", model=settings.judge_model)
    if settings.judge_provider == "anthropic":
        return AnthropicJudgeAdapter(api_key=settings.anthropic_api_key or "", model=settings.judge_model)
    return OllamaJudgeAdapter(base_url=settings.ollama_base_url)


def _build_scorers_for_suite(session: Session, eval_suite_id: uuid.UUID) -> list:
    links = (
        session.query(EvalSuiteScorer)
        .filter(EvalSuiteScorer.eval_suite_id == eval_suite_id)
        .all()
    )
    scorers = []
    for link in links:
        version: ScorerVersion | None = session.get(ScorerVersion, link.scorer_version_id)
        if version is None:
            continue
        scorer_type = version.scorer.scorer_type  # e.g. "exact_match" -- the registry key.
        # version.scorer.name is the user-facing display name (e.g. "exact_match_check")
        # and is NEVER used for registry lookup; only scorer_type is.
        if scorer_type == "llm_judge":
            adapter = _build_judge_adapter()
            rubric = version.config.get("rubric_template")  # None falls back to LLMJudgeScorer's DEFAULT_RUBRIC
            kwargs = {"adapter": adapter, "scorer_version_id": str(version.id)}
            if rubric:
                kwargs["rubric_template"] = rubric
            scorers.append(LLMJudgeScorer(**kwargs))
        else:
            scorer = core_registry.create(scorer_type, **version.config)
            scorers.append(scorer)
    return scorers


@celery_app.task(name="agenteval.score_test_case")
def score_test_case_task(
    run_id: str,
    test_case_id: str,
    actual_output,
    project_id: str,
    eval_suite_id: str,
    dataset_version_id: str,
) -> None:
    with _Session() as session:
        test_case_row = session.get(TestCaseORM, uuid.UUID(test_case_id))
        if test_case_row is None:
            raise KeyError(f"test case {test_case_id} not found")
        scorers = _build_scorers_for_suite(session, uuid.UUID(eval_suite_id))

    repo = PostgresEvalResultRepository(
        settings.database_url,
        project_id=uuid.UUID(project_id),
        dataset_version_id=uuid.UUID(dataset_version_id),
        eval_suite_id=uuid.UUID(eval_suite_id),
    )
    engine = EvalEngine(repo, scorers)

    test_case = TestCase(
        id=test_case_id,
        input=test_case_row.input,
        expected_output=test_case_row.expected_output,
        metadata=test_case_row.metadata_,
        tags=test_case_row.tags,
    )
    # score_one() reuses the exact same scoring logic as the CLI/SDK's
    # local mode -- this is the dual-mode architecture's payoff.
    result = engine.score_one(test_case, runner=lambda _: actual_output, run_id=run_id)
    repo.save_result(result)


@celery_app.task(name="agenteval.finalize_run")
def finalize_run_task(_results, run_id: str, project_id: str, eval_suite_id: str, dataset_version_id: str) -> None:
    repo = PostgresEvalResultRepository(
        settings.database_url,
        project_id=uuid.UUID(project_id),
        dataset_version_id=uuid.UUID(dataset_version_id),
        eval_suite_id=uuid.UUID(eval_suite_id),
    )
    results = repo.get_run_results(run_id)

    dummy_scorers = [_DummyScorer()]  # aggregate computation doesn't need real scorers
    engine = EvalEngine(repo, dummy_scorers)
    aggregate = engine.compute_aggregate(results)

    final_status = RunStatus.COMPLETED if aggregate.get("error_count", 0) == 0 else RunStatus.PARTIAL
    repo.update_run_status(run_id, final_status, aggregate_metrics=aggregate)


class _DummyScorer(Scorer):
    name = "_unused"
    output_type = "numeric"

    def _score(self, *a, **k):
        raise NotImplementedError("this scorer is never invoked; it satisfies EvalEngine's non-empty check")

    def score(self, *a, **k):
        raise NotImplementedError("this scorer is never invoked; it satisfies EvalEngine's non-empty check")


def dispatch_eval_run(
    run_id: str,
    project_id: str,
    eval_suite_id: str,
    dataset_version_id: str,
    test_case_ids: list[str],
    precomputed_outputs: dict[str, object],
) -> None:
    """Fan out one Celery task per test case, then a finalize task once
    all of them complete (a Celery chord).
    """
    header = [
        score_test_case_task.s(
            run_id, tc_id, precomputed_outputs.get(tc_id), project_id, eval_suite_id, dataset_version_id
        )
        for tc_id in test_case_ids
    ]
    callback = finalize_run_task.s(run_id, project_id, eval_suite_id, dataset_version_id)
    chord(header)(callback)
