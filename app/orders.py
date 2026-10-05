from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response

from app.auth import UserDep
from app.db import fetch_one
from app.discount import apply_discount
from app.errors import ApiError
from app.schemas import OrderCreate, OrderOut, ProductOut

router = APIRouter(prefix="/api", tags=["Orders"])


def order_response(row: dict) -> dict:
    return {
        "id": row["id"],
        "product_id": row["product_id"],
        "quantity": row["quantity"],
        "total": f"{Decimal(row['total_cents']) / 100:.2f}",
        "created_at": row["created_at"],
    }


@router.get("/products", response_model=list[ProductOut])
async def products(request: Request, user: UserDep) -> list[dict]:
    async with request.app.state.db.connect() as db:
        async with db.execute("SELECT * FROM products ORDER BY id") as cursor:
            return [dict(row) for row in await cursor.fetchall()]


@router.post("/orders", response_model=OrderOut, status_code=201)
async def create_order(
    payload: OrderCreate,
    request: Request,
    response: Response,
    user: UserDep,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    ],
) -> dict:
    async with request.app.state.db.connect() as db:
        # SQLite serializes writers. The key lookup and stock change share one transaction.
        await db.execute("BEGIN IMMEDIATE")
        existing = await fetch_one(
            db,
            "SELECT * FROM orders WHERE owner_id = ? AND idempotency_key = ?",
            (user["id"], idempotency_key),
        )
        if existing is not None:
            if (existing["product_id"], existing["quantity"]) != (
                payload.product_id,
                payload.quantity,
            ):
                raise ApiError(
                    409, "idempotency_conflict", "Ключ уже использован для другого заказа"
                )
            response.status_code = 200
            return order_response(existing)
        product = await fetch_one(db, "SELECT * FROM products WHERE id = ?", (payload.product_id,))
        if product is None:
            raise ApiError(404, "product_not_found", "Товар не найден")
        decreased = await db.execute(
            "UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
            (payload.quantity, payload.product_id, payload.quantity),
        )
        if decreased.rowcount != 1:
            raise ApiError(409, "insufficient_stock", "Недостаточно товара")
        amount = Decimal(product["price_cents"]) * payload.quantity / 100
        total_cents = int(apply_discount(amount) * 100)
        inserted = await db.execute(
            """INSERT INTO orders (owner_id, product_id, quantity, total_cents, idempotency_key)
               VALUES (?, ?, ?, ?, ?)""",
            (user["id"], payload.product_id, payload.quantity, total_cents, idempotency_key),
        )
        order = await fetch_one(db, "SELECT * FROM orders WHERE id = ?", (inserted.lastrowid,))
        await db.commit()
    return order_response(order)


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, request: Request, user: UserDep) -> dict:
    async with request.app.state.db.connect() as db:
        order = await fetch_one(
            db, "SELECT * FROM orders WHERE id = ? AND owner_id = ?", (order_id, user["id"])
        )
    if order is None:
        raise ApiError(404, "order_not_found", "Заказ не найден")
    return order_response(order)
