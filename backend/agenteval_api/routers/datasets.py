"""Dataset & versioned test-case management (SRS section 3.2, FR-DS-*).

Versioning is copy-on-write and IMMUTABLE once created: every Eval Run
references a specific dataset_version_id so results stay reproducible
even if someone edits the dataset later (FR-DS-3).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agenteval_api.db import get_db
from agenteval_api.deps import get_current_project_id
from agenteval_api.models.orm import Dataset, DatasetVersion, TestCaseORM
from agenteval_api.schemas.schemas import (
    DatasetCreateRequest,
    DatasetResponse,
    DatasetVersionCreateRequest,
    DatasetVersionResponse,
)

router = APIRouter(prefix="/v1/datasets", tags=["datasets"])


@router.post("", response_model=DatasetResponse, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    payload: DatasetCreateRequest,
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    if payload.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="project_id mismatch with API key scope.")
    dataset = Dataset(project_id=project_id, name=payload.name, description=payload.description)
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)
    return dataset


@router.get("", response_model=list[DatasetResponse])
async def list_datasets(db: AsyncSession = Depends(get_db), project_id: UUID = Depends(get_current_project_id)):
    result = await db.execute(select(Dataset).where(Dataset.project_id == project_id))
    return result.scalars().all()


async def _get_owned_dataset(dataset_id: UUID, db: AsyncSession, project_id: UUID) -> Dataset:
    dataset = await db.get(Dataset, dataset_id)
    if dataset is None or dataset.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found.")
    return dataset


@router.post(
    "/{dataset_id}/versions", response_model=DatasetVersionResponse, status_code=status.HTTP_201_CREATED
)
async def create_dataset_version(
    dataset_id: UUID,
    payload: DatasetVersionCreateRequest,
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    await _get_owned_dataset(dataset_id, db, project_id)

    result = await db.execute(
        select(func.max(DatasetVersion.version_number)).where(DatasetVersion.dataset_id == dataset_id)
    )
    max_version = result.scalar() or 0

    version = DatasetVersion(dataset_id=dataset_id, version_number=max_version + 1, created_by=payload.created_by)
    db.add(version)
    await db.flush()  # get version.id before adding test cases

    for tc in payload.test_cases:
        db.add(
            TestCaseORM(
                dataset_version_id=version.id,
                input=tc.input,
                expected_output=tc.expected_output,
                metadata_=tc.metadata,
                tags=tc.tags,
            )
        )

    await db.commit()
    return DatasetVersionResponse(
        id=version.id,
        dataset_id=dataset_id,
        version_number=version.version_number,
        test_case_count=len(payload.test_cases),
        created_at=version.created_at,
    )


@router.get("/{dataset_id}/versions", response_model=list[DatasetVersionResponse])
async def list_dataset_versions(
    dataset_id: UUID, db: AsyncSession = Depends(get_db), project_id: UUID = Depends(get_current_project_id)
):
    await _get_owned_dataset(dataset_id, db, project_id)
    result = await db.execute(
        select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id).order_by(DatasetVersion.version_number)
    )
    versions = result.scalars().all()
    out = []
    for v in versions:
        count_result = await db.execute(
            select(func.count()).select_from(TestCaseORM).where(TestCaseORM.dataset_version_id == v.id)
        )
        test_case_count = count_result.scalar() or 0
        out.append(
            DatasetVersionResponse(
                id=v.id,
                dataset_id=dataset_id,
                version_number=v.version_number,
                test_case_count=test_case_count,
                created_at=v.created_at,
            )
        )
    return out
