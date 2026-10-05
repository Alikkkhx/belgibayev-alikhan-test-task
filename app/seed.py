"""Explicitly create synthetic local demo data: python -m app.seed."""

import asyncio

from app.auth import password_hash
from app.db import Database, database_path


async def seed() -> None:
    db = Database(database_path())
    await db.initialize()
    hashed = await asyncio.to_thread(password_hash.hash, "Demo-password-123")
    async with db.connect() as connection:
        for name in ("alice", "bob"):
            await connection.execute(
                "INSERT OR IGNORE INTO users (email, birth_date, password_hash) VALUES (?, ?, ?)",
                (f"{name}@example.com", "2000-01-01", hashed),
            )
        await connection.execute(
            "INSERT OR IGNORE INTO products (id, name, price_cents, stock) VALUES (1, ?, ?, ?)",
            ("Учебный блокнот", 500000, 5),
        )
        await connection.commit()
    print("Demo users: alice@example.com / bob@example.com; password: Demo-password-123")
    print("Product 1: 5000.00, stock 5. Existing accounts and stock are preserved.")


if __name__ == "__main__":
    asyncio.run(seed())
