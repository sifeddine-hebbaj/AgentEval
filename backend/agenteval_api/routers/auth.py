"""Authentication: dashboard login (JWT) + API key management."""
from __future__ import annotations

from datetime import UTC
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agenteval_api.db import get_db
from agenteval_api.deps import get_current_user
from agenteval_api.models.orm import ApiKey, AuditLog, User
from agenteval_api.schemas.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    LoginRequest,
    TokenResponse,
)
from agenteval_api.security import create_access_token, generate_api_key, verify_password

router = APIRouter(prefix="/v1/auth", tags=["auth"])
keys_router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.password_hash):
        db.add(AuditLog(actor=payload.email, action="login_failed", detail={}))
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    db.add(AuditLog(actor=payload.email, action="login_succeeded", detail={}))
    await db.commit()
    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token)


@keys_router.post("", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreateRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    plaintext_key, key_prefix, key_hash = generate_api_key()
    row = ApiKey(project_id=payload.project_id, key_prefix=key_prefix, key_hash=key_hash, name=payload.name)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ApiKeyCreateResponse(id=row.id, name=row.name, plaintext_key=plaintext_key, key_prefix=key_prefix)


@keys_router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    from datetime import datetime

    row = await db.get(ApiKey, key_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")
    row.revoked_at = datetime.now(UTC)
    await db.commit()
