"""End-to-end test of the full async evaluation pipeline: trigger a run
via the API -> Celery fans out one job per test case -> workers score
against Postgres -> aggregate finalizes -> diff against a baseline.

Requires a running Postgres + Redis + Celery worker (see README).
"""
import asyncio
import time

import pytest
from httpx import ASGITransport, AsyncClient

from agenteval_api.main import app
from agenteval_api.db import SessionLocal
from agenteval_api.models.orm import ApiKey, Organization, Project
from agenteval_api.security import generate_api_key


@pytest.fixture
async def project_and_key():
    async with SessionLocal() as session:
        org = Organization(name="Pipeline Test Org")
        session.add(org)
        await session.flush()
        project = Project(org_id=org.id, name="Pipeline Test", slug=f"pipeline-{org.id}")
        session.add(project)
        await session.flush()
        plaintext_key, key_prefix, key_hash = generate_api_key()
        api_key = ApiKey(project_id=project.id, key_prefix=key_prefix, key_hash=key_hash)
        session.add(api_key)
        await session.commit()
        yield project.id, plaintext_key


async def _poll_until_complete(client, headers, run_id, timeout_s=15):
    start = time.time()
    while time.time() - start < timeout_s:
        resp = await client.get(f"/v1/eval-runs/{run_id}", headers=headers)
        data = resp.json()
        if data["status"] in ("completed", "partial", "failed"):
            return data
        await asyncio.sleep(0.5)
    raise TimeoutError(f"Eval run {run_id} did not complete within {timeout_s}s")


@pytest.mark.anyio
async def test_full_eval_run_pipeline_with_real_celery_worker(project_and_key):
    project_id, api_key = project_and_key
    headers = {"Authorization": f"Bearer {api_key}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=30) as client:
        ds_resp = await client.post("/v1/datasets", json={"project_id": str(project_id), "name": "math-qa"}, headers=headers)
        dataset_id = ds_resp.json()["id"]

        version_resp = await client.post(
            f"/v1/datasets/{dataset_id}/versions",
            json={
                "test_cases": [
                    {"input": "2+2", "expected_output": "4"},
                    {"input": "3+3", "expected_output": "6"},
                    {"input": "10+10", "expected_output": "20"},
                ]
            },
            headers=headers,
        )
        version_id = version_resp.json()["id"]

        scorer_resp = await client.post(
            "/v1/scorers",
            json={"project_id": str(project_id), "name": "exact_match_check", "scorer_type": "exact_match"},
            headers=headers,
        )
        scorer_version_id = scorer_resp.json()["id"]

        suite_resp = await client.post(
            "/v1/eval-suites",
            json={
                "project_id": str(project_id),
                "name": "core-suite",
                "scorer_version_ids": [scorer_version_id],
                "critical_scorer_version_ids": [scorer_version_id],
            },
            headers=headers,
        )
        suite_id = suite_resp.json()["id"]

        # Simulate an agent that gets everything right -- this is the "baseline" run.
        test_cases_resp = await client.get(f"/v1/datasets/{dataset_id}/versions", headers=headers)

        # Fetch actual test case IDs by re-querying the DB directly (simplest
        # way to get IDs for this test without adding a new list endpoint).
        from sqlalchemy import select
        from agenteval_api.models.orm import TestCaseORM

        async with SessionLocal() as session:
            result = await session.execute(select(TestCaseORM).where(TestCaseORM.dataset_version_id == version_id))
            test_cases = result.scalars().all()

        correct_outputs = {str(tc.id): tc.expected_output for tc in test_cases}

        baseline_run_resp = await client.post(
            "/v1/eval-runs",
            json={
                "dataset_version_id": version_id,
                "eval_suite_id": suite_id,
                "precomputed_outputs": correct_outputs,
            },
            headers=headers,
        )
        baseline_run_id = baseline_run_resp.json()["id"]
        baseline_summary = await _poll_until_complete(client, headers, baseline_run_id)

        assert baseline_summary["status"] == "completed"
        assert baseline_summary["aggregate_metrics"]["pass_rate"] == 1.0
        assert baseline_summary["aggregate_metrics"]["mean_scores"]["exact_match"] == 1.0

        await client.post(f"/v1/eval-runs/{baseline_run_id}/set-baseline", headers=headers)

        # Now simulate a REGRESSED agent: gets one test case wrong.
        broken_outputs = dict(correct_outputs)
        first_tc_id = next(iter(broken_outputs))
        broken_outputs[first_tc_id] = "WRONG_ANSWER"

        new_run_resp = await client.post(
            "/v1/eval-runs",
            json={
                "dataset_version_id": version_id,
                "eval_suite_id": suite_id,
                "precomputed_outputs": broken_outputs,
            },
            headers=headers,
        )
        new_run_id = new_run_resp.json()["id"]
        new_summary = await _poll_until_complete(client, headers, new_run_id)

        assert new_summary["aggregate_metrics"]["mean_scores"]["exact_match"] < 1.0

        diff_resp = await client.get(f"/v1/eval-runs/{new_run_id}/diff", headers=headers)
        diff = diff_resp.json()

        assert len(diff["regressed_cases"]) == 1
        assert diff["regressed_cases"][0]["test_case_id"] == first_tc_id
        assert diff["aggregate_delta"]["exact_match"] < 0
