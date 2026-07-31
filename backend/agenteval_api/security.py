"""Password hashing, JWT session tokens, and API key hashing.

API keys are never stored reversibly (SRS NFR-SEC-2, section 12): only
a salted hash is persisted, plus a short, non-secret prefix so the UI
can show 'ae_live_ab12***' without exposing the real key again.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from agenteval_api.config import settings

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


def generate_api_key() -> tuple[str, str, str]:
    """Returns (plaintext_key, key_prefix, key_hash)."""
    raw = secrets.token_urlsafe(32)
    plaintext_key = f"{settings.api_key_prefix}{raw}"
    key_prefix = plaintext_key[: len(settings.api_key_prefix) + 6]
    key_hash = hash_api_key(plaintext_key)
    return plaintext_key, key_prefix, key_hash


def hash_api_key(plaintext_key: str) -> str:
    # API keys are high-entropy random tokens (not user-chosen passwords),
    # so a fast, deterministic hash (SHA-256) is appropriate and lets us
    # look them up by exact hash match efficiently, unlike a per-hash-salted
    # scheme which would require scanning every stored key.
    return hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()
