"""EvalResultRepository: the abstraction that makes the engine dual-mode.

Both the server (PostgresEvalResultRepository, in agenteval_api) and the
local SDK/CLI (SQLiteEvalResultRepository, in agenteval_sdk) implement
this same Protocol, so agenteval_core.EvalEngine never needs to know
which backing store it's talking to.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from agenteval_core.models import EvalResult, EvalRunSummary, RunStatus


@runtime_checkable
class EvalResultRepository(Protocol):
    def create_run(self, dataset_id: str, total_test_cases: int) -> EvalRunSummary: ...

    def save_result(self, result: EvalResult) -> None: ...

    def get_run(self, run_id: str) -> EvalRunSummary: ...

    def update_run_status(
        self, run_id: str, status: RunStatus, aggregate_metrics: dict | None = None
    ) -> None: ...

    def get_run_results(self, run_id: str) -> list[EvalResult]: ...


class InMemoryEvalResultRepository:
    """Pure in-memory implementation, used for unit testing the engine
    with zero I/O. Also a useful reference implementation to compare
    the SQLite/Postgres implementations against.
    """

    def __init__(self) -> None:
        self._runs: dict[str, EvalRunSummary] = {}
        self._results: dict[str, list[EvalResult]] = {}

    def create_run(self, dataset_id: str, total_test_cases: int) -> EvalRunSummary:
        run = EvalRunSummary(dataset_id=dataset_id, total_test_cases=total_test_cases)
        self._runs[run.id] = run
        self._results[run.id] = []
        return run

    def save_result(self, result: EvalResult) -> None:
        self._results.setdefault(result.run_id, []).append(result)
        run = self._runs[result.run_id]
        run.completed_test_cases += 1

    def get_run(self, run_id: str) -> EvalRunSummary:
        return self._runs[run_id]

    def update_run_status(
        self, run_id: str, status: RunStatus, aggregate_metrics: dict | None = None
    ) -> None:
        run = self._runs[run_id]
        run.status = status
        if aggregate_metrics is not None:
            run.aggregate_metrics = aggregate_metrics

    def get_run_results(self, run_id: str) -> list[EvalResult]:
        return list(self._results.get(run_id, []))
