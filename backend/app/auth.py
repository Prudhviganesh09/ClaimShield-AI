import asyncio
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from app.db import User

# Bound memory per password operation for CPU-only hosts.
hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
auth_capacity = asyncio.Semaphore(2)
DUMMY_HASH = hasher.hash("not-a-real-user-password")


async def hash_password(password: str) -> str:
    async with auth_capacity:
        return await asyncio.to_thread(hasher.hash, password)


async def verify_password(password: str, encoded: str) -> bool:
    async with auth_capacity:
        try:
            return await asyncio.to_thread(hasher.verify, encoded, password)
        except (VerificationError, InvalidHashError):
            return False


def set_session(response, user: User, settings):
    token = jwt.encode({"sub": user.id, "exp": datetime.now(UTC) + timedelta(hours=8),
                        "iat": datetime.now(UTC), "iss": "claimshield", "aud": "claimshield"},
                       settings.jwt_secret.get_secret_value(), algorithm="HS256")
    response.set_cookie("claimshield_session", token, httponly=True, secure=settings.cookie_secure,
                        samesite="strict", max_age=8*3600, path="/")


async def current_user(request: Request) -> User:
    token = request.cookies.get("claimshield_session")
    if not token:
        raise HTTPException(401, "Sign in to continue")
    try:
        payload = jwt.decode(token, request.app.state.settings.jwt_secret.get_secret_value(),
                             algorithms=["HS256"], issuer="claimshield", audience="claimshield",
                             options={"require": ["exp", "iat", "sub", "iss", "aud"]})
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Your session expired. Sign in again") from exc
    async with request.app.state.db.sessions() as session:
        user = await session.scalar(select(User).where(User.id == payload["sub"]))
    if not user:
        raise HTTPException(401, "Session user no longer exists")
    return user


async def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required")
    return user


def public_user(user: User):
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}
