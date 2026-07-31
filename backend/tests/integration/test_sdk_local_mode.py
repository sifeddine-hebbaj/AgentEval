"""Proves the SDK's local mode works fully offline: no server, no
Docker, just pip install and go (NFR-USE-1's spirit).
"""
from pathlib import Path

from agenteval_core.scorers.deterministic import ExactMatchScorer
from agenteval_sdk.client import Client


def test_local_client_full_loop(tmp_path: Path):
    dataset_file = tmp_path / "data.jsonl"
    dataset_file.write_text(
        '{"input": "2+2", "expected_output": "4"}\n'
        '{"input": "10+5", "expected_output": "15"}\n'
    )

    db_path = str(tmp_path / "local.db")
    client = Client(local=True, local_db_path=db_path)

    dataset = client.load_dataset(str(dataset_file))
    assert len(dataset.test_cases) == 2

    def runner(x: str) -> str:
        a, b = x.split("+")
        return str(int(a) + int(b))

    summary = client.run_eval(dataset, runner, scorers=[ExactMatchScorer()])
    assert summary.aggregate_metrics["pass_rate"] == 1.0

    results = client.get_run_results(summary.id)
    assert len(results) == 2
    assert all(r.status == "ok" for r in results)

    # Reopen a fresh client against the same DB path to prove persistence
    client2 = Client(local=True, local_db_path=db_path)
    persisted_results = client2.get_run_results(summary.id)
    assert len(persisted_results) == 2
