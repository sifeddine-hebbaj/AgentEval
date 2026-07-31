"""EvalEngine: the orchestration core reused by both the local CLI/SDK
and the server-side Celery workers (see SRS section 5.6 - the
"dual-mode" constraint). Do not put orchestration logic anywhere else;
if you find yourself re-implementing "loop over test cases and call
scorers" in the API or worker layer, import this instead.
"""
from __future__ import annotations

import inspect
import time
from statistics import mean, median
from typing import Any, Awaitable, Callable

from agenteval_core.models import Dataset, EvalResult, EvalRunSummary, RunStatus, TestCase
from agenteval_core.repository import EvalResultRepository
from agenteval_core.scorers.base import Scorer

Runner = Callable[[Any], Any] | Callable[[Any], Awaitable[Any]]


class EvalEngine:
    def __init__(self, repository: EvalResultRepository, scorers: list[Scorer]) -> None:
        if not scorers:
            raise ValueError("EvalEngine requires at least one scorer")
        self.repository = repository
        self.scorers = scorers

    def _invoke_runner(self, runner: Runner, test_case: TestCase) -> Any:
        if inspect.iscoroutinefunction(runner):
            import asyncio

            return asyncio.run(runner(test_case.input))  # type: ignore[arg-type]
        return runner(test_case.input)

    def score_one(self, test_case: TestCase, runner: Runner, run_id: str) -> EvalResult:
        """Execute the runner + all scorers for a single test case.
        Isolated so a failure here never aborts the whole batch (NFR-AVAIL-3).
        """
        start = time.perf_counter()
        try:
            actual_output = self._invoke_runner(runner, test_case)
            status, error_message = "ok", None
        except Exception as exc:  # noqa: BLE001 - intentional: isolate runner failures
            actual_output, status, error_message = None, "error", f"{type(exc).__name__}: {exc}"

        latency_ms = int((time.perf_counter() - start) * 1000)
        metadata = {**test_case.metadata, "latency_ms": latency_ms}

        scores = {}
        if status == "ok":
            for scorer in self.scorers:
                scores[scorer.name] = scorer.score(
                    test_case.input, actual_output, test_case.expected_output, metadata
                )

        return EvalResult(
            run_id=run_id,
            test_case_id=test_case.id,
            actual_output=actual_output,
            status=status,
            error_message=error_message,
            latency_ms=latency_ms,
            scores=scores,
        )

    def run(self, dataset: Dataset, runner: Runner) -> EvalRunSummary:
        run = self.repository.create_run(dataset_id=dataset.id, total_test_cases=len(dataset.test_cases))
        self.repository.update_run_status(run.id, RunStatus.RUNNING)

        for test_case in dataset.test_cases:
            result = self.score_one(test_case, runner, run.id)
            self.repository.save_result(result)

        aggregate = self.compute_aggregate(self.repository.get_run_results(run.id))
        final_status = RunStatus.COMPLETED if aggregate.get("error_count", 0) == 0 else RunStatus.PARTIAL
        self.repository.update_run_status(run.id, final_status, aggregate_metrics=aggregate)
        return self.repository.get_run(run.id)

    def compute_aggregate(self, results: list[EvalResult]) -> dict[str, Any]:
        per_scorer: dict[str, list[float]] = {}
        pass_count = 0
        error_count = 0
        latencies: list[int] = []

        for result in results:
            if result.status == "error":
                error_count += 1
                continue
            latencies.append(result.latency_ms or 0)
            all_passed = True
            for scorer_name, score in result.scores.items():
                if score.error is not None:
                    all_passed = False
                    continue
                if score.numeric_value is not None:
                    per_scorer.setdefault(scorer_name, []).append(score.numeric_value)
                elif score.boolean_value is not None:
                    per_scorer.setdefault(scorer_name, []).append(1.0 if score.boolean_value else 0.0)
                if not score.passed():
                    all_passed = False
            if all_passed:
                pass_count += 1

        latencies.sort()

        def _pct(values: list[int], p: float) -> int:
            if not values:
                return 0
            idx = min(len(values) - 1, int(len(values) * p))
            return values[idx]

        return {
            "mean_scores": {name: round(mean(vals), 4) for name, vals in per_scorer.items() if vals},
            "median_scores": {name: round(median(vals), 4) for name, vals in per_scorer.items() if vals},
            "pass_rate": round(pass_count / len(results), 4) if results else 0.0,
            "error_count": error_count,
            "total": len(results),
            "p50_latency_ms": _pct(latencies, 0.5),
            "p95_latency_ms": _pct(latencies, 0.95),
        }
