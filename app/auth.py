import asyncio
import hashlib
import secrets
import time
from typing import Annotated

import aiosqlite
from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash

from app.db import fetch_one
from app.errors import ApiError
from app.schemas import Login, Registration, TokenOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["Auth"])
password_hash = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)
SESSION_TTL = 1800


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> dict:
    if credentials is None or len(credentials.credentials) > 256:
        raise ApiError(401, "unauthorized", "Войдите в аккаунт")
    async with request.app.state.db.connect() as db:
        row = await fetch_one(
            db,
            """SELECT u.id, u.email, u.birth_date FROM sessions s
               JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?""",
            (token_hash(credentials.credentials), int(time.time())),
        )
    if row is None:
        raise ApiError(401, "unauthorized", "Сессия недействительна или истекла")
    return dict(row)


UserDep = Annotated[dict, Depends(current_user)]


@router.post("/register", response_model=UserOut, status_code=201)
async def register(payload: Registration, request: Request) -> dict:
    hashed = await asyncio.to_thread(password_hash.hash, payload.password)
    async with request.app.state.db.connect() as db:
        try:
            cursor = await db.execute(
                "INSERT INTO users (email, birth_date, password_hash) VALUES (?, ?, ?)",
                (str(payload.email), payload.birth_date.isoformat(), hashed),
            )
            await db.commit()
        except aiosqlite.IntegrityError as exc:
            raise ApiError(
                409,
                "email_taken",
                "Адрес уже зарегистрирован",
                {"email": "Этот email уже занят. Войдите или укажите другой."},
            ) from exc
    return {"id": cursor.lastrowid, "email": str(payload.email), "birth_date": payload.birth_date}


@router.post("/login", response_model=TokenOut)
async def login(payload: Login, request: Request) -> dict:
    async with request.app.state.db.connect() as db:
        user = await fetch_one(db, "SELECT * FROM users WHERE email = ?", (str(payload.email),))
        if user is None or not await asyncio.to_thread(
            password_hash.verify, payload.password, user["password_hash"]
        ):
            raise ApiError(401, "invalid_credentials", "Неверный email или пароль")
        token = secrets.token_urlsafe(32)
        await db.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (token_hash(token), user["id"], int(time.time()) + SESSION_TTL),
        )
        await db.commit()
    return {"access_token": token, "token_type": "bearer", "expires_in": SESSION_TTL}


@router.get("/me", response_model=UserOut)
async def me(user: UserDep) -> dict:
    return user


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    user: UserDep,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> Response:
    async with request.app.state.db.connect() as db:
        await db.execute(
            "DELETE FROM sessions WHERE token_hash = ?", (token_hash(credentials.credentials),)
        )
        await db.commit()
    return Response(status_code=204)
