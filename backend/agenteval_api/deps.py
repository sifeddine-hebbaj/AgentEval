"""Shared FastAPI dependencies: DB session, current project (API key
auth), current user (JWT session auth).

Critical invariant (SRS section 12.2): every route that touches
tenant-scoped data depends on get_current_project, which derives
project_id from the authenticated principal -- NEVER from the request
body/path alone. This makes cross-tenant leaks structurally harder to
introduce by accident in a new route.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agenteval_api.db import get_db
from agenteval_api.models.orm import ApiKey, User
from agenteval_api.security import decode_access_token, hash_api_key


async def get_current_project_id(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> UUID:
    if authorization is None or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Expected 'Bearer <api_key>'.",
        )
    plaintext_key = authorization.split(" ", 1)[1].strip()
    key_hash = hash_api_key(plaintext_key)

    result = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    api_key = result.scalar_one_or_none()

    if api_key is None or api_key.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key.")

    return api_key.project_id


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if authorization is None or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing session token.")
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session token.")

    result = await db.execute(select(User).where(User.id == UUID(payload["sub"])))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists.")
    return user
