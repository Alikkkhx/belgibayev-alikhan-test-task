from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.auth import UserDep
from app.db import fetch_one
from app.errors import ApiError
from app.schemas import TaskCreate, TaskOut, TaskPage, TaskStatus, TaskUpdate

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(payload: TaskCreate, request: Request, user: UserDep) -> dict:
    async with request.app.state.db.connect() as db:
        cursor = await db.execute(
            "INSERT INTO tasks (owner_id, title) VALUES (?, ?)", (user["id"], payload.title)
        )
        task = await fetch_one(db, "SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,))
        await db.commit()
    return dict(task)


@router.get("", response_model=TaskPage)
async def list_tasks(
    request: Request,
    user: UserDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: TaskStatus | None = None,
) -> dict:
    where = "owner_id = ?"
    parameters = (user["id"],)
    if status is not None:
        where += " AND status = ?"
        parameters += (status.value,)
    async with request.app.state.db.connect() as db:
        # One read transaction gives count and page the same database snapshot.
        await db.execute("BEGIN")
        total = (await fetch_one(db, f"SELECT count(*) AS n FROM tasks WHERE {where}", parameters))[
            "n"
        ]
        async with db.execute(
            f"SELECT * FROM tasks WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
            (*parameters, limit, offset),
        ) as cursor:
            items = [dict(row) for row in await cursor.fetchall()]
    next_offset = offset + len(items) if offset + len(items) < total else None
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": next_offset,
    }


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: int, request: Request, user: UserDep) -> dict:
    async with request.app.state.db.connect() as db:
        task = await fetch_one(
            db, "SELECT * FROM tasks WHERE id = ? AND owner_id = ?", (task_id, user["id"])
        )
    if task is None:
        raise ApiError(404, "task_not_found", "Задача не найдена")
    return dict(task)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(task_id: int, payload: TaskUpdate, request: Request, user: UserDep) -> dict:
    async with request.app.state.db.connect() as db:
        cursor = await db.execute(
            "UPDATE tasks SET status = ? WHERE id = ? AND owner_id = ?",
            (payload.status.value, task_id, user["id"]),
        )
        if cursor.rowcount == 0:
            raise ApiError(404, "task_not_found", "Задача не найдена")
        task = await fetch_one(db, "SELECT * FROM tasks WHERE id = ?", (task_id,))
        await db.commit()
    return dict(task)


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: int, request: Request, user: UserDep) -> Response:
    async with request.app.state.db.connect() as db:
        cursor = await db.execute(
            "DELETE FROM tasks WHERE id = ? AND owner_id = ?", (task_id, user["id"])
        )
        if cursor.rowcount == 0:
            raise ApiError(404, "task_not_found", "Задача не найдена")
        await db.commit()
    return Response(status_code=204)
