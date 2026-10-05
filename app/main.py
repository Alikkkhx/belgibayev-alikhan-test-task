import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from app import auth, orders, tasks
from app.db import Database, database_path
from app.errors import ApiError
from app.schemas import ErrorOut

logger = logging.getLogger("test_task")


def error_response(
    request: Request, status: int, code: str, message: str, fields: dict | None = None
) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
    return JSONResponse(
        status_code=status,
        headers=headers,
        content={
            "error": {
                "code": code,
                "message": message,
                "fields": fields or {},
                "request_id": getattr(request.state, "request_id", "unknown"),
            }
        },
    )


def create_app(path: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.db = Database(path if path is not None else database_path())
        await application.state.db.initialize()
        yield

    application = FastAPI(
        title="Практический тест — Бельгибаев Алихан",
        version="0.1.0",
        lifespan=lifespan,
        responses={code: {"model": ErrorOut} for code in (401, 404, 409, 422, 500, 503)},
    )

    @application.middleware("http")
    async def request_log(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        # No request body, bearer token, password, email or query string in this log.
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        logger.info(
            "request_id=%s method=%s route=%s status=%s duration_ms=%.1f",
            request.state.request_id,
            request.method,
            route_path,
            response.status_code,
            (time.perf_counter() - start) * 1000,
        )
        return response

    @application.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return error_response(request, exc.status, exc.code, exc.message, exc.fields)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        fields = {}
        for error in exc.errors():
            name = ".".join(str(part) for part in error["loc"][1:]) or "body"
            message = error["msg"].removeprefix("Value error, ")
            if error["type"] == "missing":
                message = "Обязательное поле"
            elif name == "email":
                message = "Укажите корректный email, например name@example.com"
            elif name == "password":
                message = "Пароль должен содержать от 10 до 128 символов"
            fields[name] = message
        return error_response(request, 422, "validation_error", "Проверьте поля формы", fields)

    @application.exception_handler(aiosqlite.DatabaseError)
    async def database_error(request: Request, exc: aiosqlite.DatabaseError):
        logger.error(
            "request_id=%s database_error=%s", request.state.request_id, type(exc).__name__
        )
        busy = isinstance(exc, aiosqlite.OperationalError) and "locked" in str(exc).lower()
        if busy:
            return error_response(request, 503, "database_busy", "Сервис занят. Повторите позже.")
        return error_response(request, 500, "database_error", "Не удалось сохранить данные")

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(request, exc.status_code, "http_error", str(exc.detail))

    @application.get("/health", tags=["Health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(auth.router)
    application.include_router(tasks.router)
    application.include_router(orders.router)
    static = Path(__file__).resolve().parent / "static"
    if static.exists():
        application.mount("/", StaticFiles(directory=static, html=True), name="web")
    return application


app = create_app()
