"""Integration tests against a REAL Postgres instance (not mocked).

Requires DATABASE_URL to point at a running Postgres with migrations
applied (see README 'Running Tests' section). These are the tests that
prove auth scoping, trace ingestion, and dataset versioning actually
work end-to-end, not just in isolation.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from agenteval_api.main import app
from agenteval_api.db import SessionLocal
from agenteval_api.models.orm import Organization, Project, ApiKey, User
from agenteval_api.security import generate_api_key, hash_password


@pytest.fixture
async def project_and_key():
    async with SessionLocal() as session:
        org = Organization(name="Test Org")
        session.add(org)
        await session.flush()

        project = Project(org_id=org.id, name="Test Project", slug=f"test-{org.id}")
        session.add(project)
        await session.flush()

        plaintext_key, key_prefix, key_hash = generate_api_key()
        api_key = ApiKey(project_id=project.id, key_prefix=key_prefix, key_hash=key_hash, name="test-key")
        session.add(api_key)
        await session.commit()

        yield project.id, plaintext_key


@pytest.fixture
async def other_project_and_key():
    async with SessionLocal() as session:
        org = Organization(name="Other Org")
        session.add(org)
        await session.flush()
        project = Project(org_id=org.id, name="Other Project", slug=f"other-{org.id}")
        session.add(project)
        await session.flush()
        plaintext_key, key_prefix, key_hash = generate_api_key()
        api_key = ApiKey(project_id=project.id, key_prefix=key_prefix, key_hash=key_hash, name="other-key")
        session.add(api_key)
        await session.commit()
        yield project.id, plaintext_key


@pytest.mark.anyio
async def test_trace_ingestion_and_retrieval(project_and_key):
    project_id, api_key = project_and_key
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {
            "environment": "production",
            "metadata": {"session_id": "abc123"},
            "spans": [
                {
                    "span_type": "llm_call",
                    "name": "generate_response",
                    "input": {"prompt": "hello"},
                    "output": {"text": "hi there"},
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "cost": 0.001,
                }
            ],
        }
        resp = await client.post("/v1/traces", json=payload, headers=headers)
        assert resp.status_code == 202
        trace_id = resp.json()["id"]

        get_resp = await client.get(f"/v1/traces/{trace_id}", headers=headers)
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["environment"] == "production"
        assert data["total_tokens"] == 15
        assert len(data["spans"]) == 1


@pytest.mark.anyio
async def test_cross_tenant_trace_access_is_denied(project_and_key, other_project_and_key):
    """The single most important security regression test in the system
    (SRS section 12.2): a trace created under one project must be
    invisible to a different project's API key, even with the correct ID.
    """
    project_id, api_key = project_and_key
    _, other_api_key = other_project_and_key

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = await client.post("/v1/traces", json={"environment": "development", "spans": []}, headers=headers)
        trace_id = resp.json()["id"]

        other_headers = {"Authorization": f"Bearer {other_api_key}"}
        cross_tenant_resp = await client.get(f"/v1/traces/{trace_id}", headers=other_headers)
        assert cross_tenant_resp.status_code == 404  # not 403 -- don't even confirm it exists


@pytest.mark.anyio
async def test_invalid_api_key_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/traces", headers={"Authorization": "Bearer ae_live_totally_fake_key"})
        assert resp.status_code == 401


@pytest.mark.anyio
async def test_dataset_versioning_is_immutable(project_and_key):
    project_id, api_key = project_and_key
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {api_key}"}
        ds_resp = await client.post(
            "/v1/datasets", json={"project_id": str(project_id), "name": "support-qa"}, headers=headers
        )
        assert ds_resp.status_code == 201
        dataset_id = ds_resp.json()["id"]

        v1_resp = await client.post(
            f"/v1/datasets/{dataset_id}/versions",
            json={"test_cases": [{"input": "what is 2+2", "expected_output": "4"}]},
            headers=headers,
        )
        assert v1_resp.status_code == 201
        assert v1_resp.json()["version_number"] == 1
        assert v1_resp.json()["test_case_count"] == 1

        v2_resp = await client.post(
            f"/v1/datasets/{dataset_id}/versions",
            json={"test_cases": [{"input": "what is 3+3", "expected_output": "6"}, {"input": "what is 5+5", "expected_output": "10"}]},
            headers=headers,
        )
        assert v2_resp.status_code == 201
        assert v2_resp.json()["version_number"] == 2
        assert v2_resp.json()["test_case_count"] == 2

        versions_resp = await client.get(f"/v1/datasets/{dataset_id}/versions", headers=headers)
        versions = versions_resp.json()
        assert len(versions) == 2
        assert versions[0]["test_case_count"] == 1  # v1 untouched by v2's creation
        assert versions[1]["test_case_count"] == 2
