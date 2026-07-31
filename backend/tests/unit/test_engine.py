import pytest

from agenteval_core.models import Dataset, RunStatus, TestCase
from agenteval_core.engine import EvalEngine
from agenteval_core.repository import InMemoryEvalResultRepository
from agenteval_core.scorers.deterministic import ExactMatchScorer


def make_dataset():
    return Dataset(
        name="unit-test-ds",
        test_cases=[
            TestCase(input="2+2", expected_output="4"),
            TestCase(input="3+3", expected_output="6"),
            TestCase(input="5+5", expected_output="10"),
        ],
    )


def test_engine_run_computes_correct_aggregate():
    def runner(x: str) -> str:
        a, b = x.split("+")
        return str(int(a) + int(b))

    engine = EvalEngine(InMemoryEvalResultRepository(), [ExactMatchScorer()])
    summary = engine.run(make_dataset(), runner)

    assert summary.status == RunStatus.COMPLETED
    assert summary.completed_test_cases == 3
    assert summary.aggregate_metrics["pass_rate"] == 1.0
    assert summary.aggregate_metrics["error_count"] == 0


def test_engine_one_failing_test_case_does_not_abort_run():
    calls = {"n": 0}

    def flaky_runner(x: str) -> str:
        calls["n"] += 1
        if x == "3+3":
            raise RuntimeError("simulated failure")
        a, b = x.split("+")
        return str(int(a) + int(b))

    engine = EvalEngine(InMemoryEvalResultRepository(), [ExactMatchScorer()])
    summary = engine.run(make_dataset(), flaky_runner)

    assert calls["n"] == 3  # all test cases were attempted
    assert summary.completed_test_cases == 3
    assert summary.aggregate_metrics["error_count"] == 1
    assert summary.status == RunStatus.PARTIAL


def test_engine_requires_at_least_one_scorer():
    with pytest.raises(ValueError):
        EvalEngine(InMemoryEvalResultRepository(), [])


def test_engine_supports_async_runner():
    async def async_runner(x: str) -> str:
        a, b = x.split("+")
        return str(int(a) + int(b))

    engine = EvalEngine(InMemoryEvalResultRepository(), [ExactMatchScorer()])
    summary = engine.run(make_dataset(), async_runner)
    assert summary.aggregate_metrics["pass_rate"] == 1.0
