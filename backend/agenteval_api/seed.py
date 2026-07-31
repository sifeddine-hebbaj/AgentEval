"""Creates a demo organization, project, and API key for local exploration.

Run via: python -m agenteval_api.seed   (or `make seed` against the
Docker Compose stack). Safe to re-run -- it checks for an existing
"Demo Org" before creating a new one.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from agenteval_api.db import SessionLocal
from agenteval_api.models.orm import ApiKey, Organization, Project
from agenteval_api.security import generate_api_key


async def main() -> None:
    async with SessionLocal() as session:
        result = await session.execute(select(Organization).where(Organization.name == "Demo Org"))
        org = result.scalar_one_or_none()
        if org is None:
            org = Organization(name="Demo Org")
            session.add(org)
            await session.flush()

        result = await session.execute(select(Project).where(Project.slug == "demo-project"))
        project = result.scalar_one_or_none()
        if project is None:
            project = Project(org_id=org.id, name="Demo Project", slug="demo-project")
            session.add(project)
            await session.flush()

        plaintext_key, key_prefix, key_hash = generate_api_key()
        api_key = ApiKey(project_id=project.id, key_prefix=key_prefix, key_hash=key_hash, name="seed-key")
        session.add(api_key)
        await session.commit()

        print("=" * 60)
        print("Demo project created.")
        print(f"  project_id: {project.id}")
        print(f"  api_key:    {plaintext_key}")
        print("=" * 60)
        print("Paste the api_key above into the dashboard login screen,")
        print("or use it as AGENTEVAL_API_KEY for the SDK/CLI.")


if __name__ == "__main__":
    asyncio.run(main())
