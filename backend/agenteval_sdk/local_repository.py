"""SQLite-backed EvalResultRepository for fully offline/local usage.

Implements the exact same Protocol as the server's Postgres repository
(agenteval_api.repositories.postgres_repo.PostgresEvalResultRepository)
so agenteval_core.EvalEngine's orchestration logic never changes between
local and networked usage.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agenteval_core.models import EvalResult, EvalRunSummary, RunStatus, ScoreResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    status TEXT NOT NULL,
    total_test_cases INTEGER NOT NULL,
    completed_test_cases INTEGER NOT NULL DEFAULT 0,
    aggregate_metrics TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS eval_results (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    test_case_id TEXT NOT NULL,
    actual_output TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    latency_ms INTEGER,
    scores TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES eval_runs(id)
);
CREATE INDEX IF NOT EXISTS idx_eval_results_run_id ON eval_results(run_id);
"""


class SQLiteEvalResultRepository:
    def __init__(self, db_path: str = ".agenteval/local.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def create_run(self, dataset_id: str, total_test_cases: int) -> EvalRunSummary:
        run = EvalRunSummary(dataset_id=dataset_id, total_test_cases=total_test_cases)
        self.conn.execute(
            "INSERT INTO eval_runs (id, dataset_id, status, total_test_cases, completed_test_cases, "
            "aggregate_metrics, started_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.id,
                run.dataset_id,
                run.status.value,
                run.total_test_cases,
                0,
                "{}",
                run.started_at.isoformat(),
                None,
            ),
        )
        self.conn.commit()
        return run

    def save_result(self, result: EvalResult) -> None:
        scores_json = json.dumps({k: v.model_dump() for k, v in result.scores.items()}, default=str)
        self.conn.execute(
            "INSERT INTO eval_results (id, run_id, test_case_id, actual_output, status, "
            "error_message, latency_ms, scores, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                result.id,
                result.run_id,
                result.test_case_id,
                json.dumps(result.actual_output, default=str),
                result.status,
                result.error_message,
                result.latency_ms,
                scores_json,
                result.created_at.isoformat(),
            ),
        )
        self.conn.execute(
            "UPDATE eval_runs SET completed_test_cases = completed_test_cases + 1 WHERE id = ?",
            (result.run_id,),
        )
        self.conn.commit()

    def get_run(self, run_id: str) -> EvalRunSummary:
        row = self.conn.execute("SELECT * FROM eval_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"eval run {run_id} not found")
        cols = [c[0] for c in self.conn.execute("SELECT * FROM eval_runs LIMIT 0").description]
        data = dict(zip(cols, row))
        return EvalRunSummary(
            id=data["id"],
            dataset_id=data["dataset_id"],
            status=RunStatus(data["status"]),
            total_test_cases=data["total_test_cases"],
            completed_test_cases=data["completed_test_cases"],
            aggregate_metrics=json.loads(data["aggregate_metrics"]),
            started_at=data["started_at"],
            completed_at=data["completed_at"],
        )

    def update_run_status(
        self, run_id: str, status: RunStatus, aggregate_metrics: dict | None = None
    ) -> None:
        if aggregate_metrics is not None:
            self.conn.execute(
                "UPDATE eval_runs SET status = ?, aggregate_metrics = ?, completed_at = datetime('now') "
                "WHERE id = ?",
                (status.value, json.dumps(aggregate_metrics), run_id),
            )
        else:
            self.conn.execute("UPDATE eval_runs SET status = ? WHERE id = ?", (status.value, run_id))
        self.conn.commit()

    def get_run_results(self, run_id: str) -> list[EvalResult]:
        cols = [c[0] for c in self.conn.execute("SELECT * FROM eval_results LIMIT 0").description]
        rows = self.conn.execute(
            "SELECT * FROM eval_results WHERE run_id = ?", (run_id,)
        ).fetchall()
        results = []
        for row in rows:
            data = dict(zip(cols, row))
            scores = {
                k: ScoreResult(**v) for k, v in json.loads(data["scores"]).items()
            }
            results.append(
                EvalResult(
                    id=data["id"],
                    run_id=data["run_id"],
                    test_case_id=data["test_case_id"],
                    actual_output=json.loads(data["actual_output"]) if data["actual_output"] else None,
                    status=data["status"],
                    error_message=data["error_message"],
                    latency_ms=data["latency_ms"],
                    scores=scores,
                    created_at=data["created_at"],
                )
            )
        return results

    def get_result(self, test_case_id: str) -> EvalResult | None:
        cols = [c[0] for c in self.conn.execute("SELECT * FROM eval_results LIMIT 0").description]
        row = self.conn.execute(
            "SELECT * FROM eval_results WHERE test_case_id = ? ORDER BY created_at DESC LIMIT 1", (test_case_id,)
        ).fetchone()
        if row is None:
            return None
        data = dict(zip(cols, row))
        scores = {
            k: ScoreResult(**v) for k, v in json.loads(data["scores"]).items()
        }
        return EvalResult(
            id=data["id"],
            run_id=data["run_id"],
            test_case_id=data["test_case_id"],
            actual_output=json.loads(data["actual_output"]) if data["actual_output"] else None,
            status=data["status"],
            error_message=data["error_message"],
            latency_ms=data["latency_ms"],
            scores=scores,
            created_at=data["created_at"],
        )
