"""AgentEval SDK Client.

Two modes, same public interface:
  * Client(local=True): pure local dev loop, no server, SQLite-backed.
  * Client(api_key=..., base_url=...): talks to a running AgentEval API,
    buffers trace flushing on a background thread so it never blocks the
    calling agent (NFR-AVAIL-2), with local-disk fallback on outage.
"""
from __future__ import annotations

import atexit
import queue
import threading
import time
from typing import Any, Optional

from agenteval_core.engine import EvalEngine
from agenteval_core.models import Dataset, EvalRunSummary, Trace
from agenteval_core.scorers.base import Scorer
from agenteval_sdk.local_repository import SQLiteEvalResultRepository
from agenteval_sdk.tracing import DiskFallbackQueue


class Client:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "http://localhost:8000",
        project: str | None = None,
        local: bool = False,
        local_db_path: str = ".agenteval/local.db",
        flush_interval_seconds: float = 2.0,
    ) -> None:
        self.local = local
        self.project = project
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

        if not local and not api_key:
            raise ValueError("Client requires api_key unless local=True")

        if local:
            self._repository = SQLiteEvalResultRepository(local_db_path)
        else:
            self._repository = None  # server owns the repository in network mode

        self._fallback_queue = DiskFallbackQueue()
        self._send_queue: "queue.Queue[Trace]" = queue.Queue(maxsize=10_000)
        self._stop_event = threading.Event()
        if not local:
            self._flush_thread = threading.Thread(
                target=self._flush_loop, args=(flush_interval_seconds,), daemon=True
            )
            self._flush_thread.start()
            atexit.register(self.flush)

    # -- Tracing -------------------------------------------------------------

    def _enqueue_trace(self, trace_obj: Trace) -> None:
        if self.local:
            return  # local mode: traces aren't persisted separately from eval results
        try:
            self._send_queue.put_nowait(trace_obj)
        except queue.Full:
            self._fallback_queue.push(trace_obj)

    def _flush_loop(self, interval: float) -> None:
        while not self._stop_event.is_set():
            time.sleep(interval)
            self.flush()

    def flush(self) -> None:
        """Send all buffered traces. Never raises into caller code --
        failures fall back to local disk and are retried on the next
        flush cycle (NFR-AVAIL-2).
        """
        import httpx

        pending: list[Trace] = list(self._fallback_queue.drain())
        while True:
            try:
                pending.append(self._send_queue.get_nowait())
            except queue.Empty:
                break

        if not pending:
            return

        try:
            with httpx.Client(base_url=self.base_url, timeout=10.0) as http:
                for t in pending:
                    resp = http.post(
                        "/v1/traces",
                        json=t.model_dump(mode="json"),
                        headers={"Authorization": f"Bearer {self.api_key}"},
                    )
                    resp.raise_for_status()
        except Exception:
            for t in pending:
                self._fallback_queue.push(t)

    # -- Datasets --------------------------------------------------------------

    def load_dataset(self, path: str) -> Dataset:
        if path.endswith(".jsonl"):
            return Dataset.from_jsonl(path)
        if path.endswith(".csv"):
            return Dataset.from_csv(path)
        raise ValueError(f"Unsupported dataset file type: {path}")

    # -- Eval runs (local mode) --------------------------------------------------

    def run_eval(self, dataset: Dataset, runner, scorers: list[Scorer]) -> EvalRunSummary:
        if not self.local:
            raise RuntimeError(
                "run_eval() runs evaluations in-process; use local=True for this, "
                "or trigger a server-side run via trigger_remote_eval_run()."
            )
        engine = EvalEngine(self._repository, scorers)
        return engine.run(dataset, runner)

    def get_run_results(self, run_id: str):
        if not self.local:
            raise RuntimeError("get_run_results() is only available in local mode via the SDK")
        return self._repository.get_run_results(run_id)

    # -- Eval runs (remote/server mode) ------------------------------------------

    def trigger_remote_eval_run(
        self, dataset_version_id: str, eval_suite_id: str, git_sha: str | None = None
    ) -> dict[str, Any]:
        import httpx

        with httpx.Client(base_url=self.base_url, timeout=30.0) as http:
            resp = http.post(
                "/v1/eval-runs",
                json={
                    "dataset_version_id": dataset_version_id,
                    "eval_suite_id": eval_suite_id,
                    "trigger_source": "sdk",
                    "git_sha": git_sha,
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()
            return resp.json()
