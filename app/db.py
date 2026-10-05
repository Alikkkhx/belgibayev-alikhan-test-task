import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


def database_path() -> Path:
    return Path(os.environ.get("DATABASE_PATH", "data/app.db"))


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self.path, timeout=5) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.execute("PRAGMA busy_timeout = 5000")
            yield connection
            # Closing an uncommitted connection rolls back its transaction.

    async def initialize(self) -> None:
        await asyncio.to_thread(self.path.parent.mkdir, parents=True, exist_ok=True)
        schema = await asyncio.to_thread(
            Path(__file__).with_name("schema.sql").read_text, encoding="utf-8"
        )
        async with self.connect() as connection:
            await connection.executescript(schema)
            await connection.commit()


async def fetch_one(
    connection: aiosqlite.Connection, sql: str, parameters: tuple = ()
) -> aiosqlite.Row | None:
    async with connection.execute(sql, parameters) as cursor:
        return await cursor.fetchone()
