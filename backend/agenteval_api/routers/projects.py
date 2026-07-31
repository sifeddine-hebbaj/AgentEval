"""Organizations & Projects."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from agenteval_api.db import get_db
from agenteval_api.deps import get_current_user
from agenteval_api.models.orm import Organization, Project, User
from agenteval_api.schemas.schemas import ProjectCreateRequest, ProjectResponse

router = APIRouter(prefix="/v1/projects", tags=["projects"])
org_router = APIRouter(prefix="/v1/organizations", tags=["organizations"])


@org_router.post("", status_code=status.HTTP_201_CREATED)
async def create_organization(name: str, db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)):
    org = Organization(name=name)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return {"id": org.id, "name": org.name}


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = Project(org_id=payload.org_id, name=payload.name, slug=payload.slug)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project
