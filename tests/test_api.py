import asyncio

import pytest


async def test_health_and_openapi(api):
    client, _ = api
    assert (await client.get("/health")).json() == {"status": "ok"}
    schema = (await client.get("/openapi.json")).json()
    assert "/api/tasks" in schema["paths"]
    assert (await client.get("/docs")).status_code == 200


async def test_registration_duplicate_email_and_no_password_leak(users):
    client, _, _, _ = users
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "ALICE@example.com",
            "birth_date": "2000-01-01",
            "password": "Other-password-123",
        },
    )
    assert response.status_code == 409
    assert "email" in response.json()["error"]["fields"]
    assert "password" not in response.text


async def test_server_validation_without_frontend(api):
    client, _ = api
    response = await client.post(
        "/api/auth/register",
        json={"email": "bad", "birth_date": "2999-01-01", "password": "secret"},
    )
    assert response.status_code == 422
    assert set(response.json()["error"]["fields"]) == {"email", "birth_date", "password"}
    assert "secret" not in response.text
    assert response.headers["x-request-id"]


async def test_task_crud_and_ownership(users):
    client, _, alice, bob = users
    created = await client.post("/api/tasks", headers=alice, json={"title": "Read FastAPI"})
    assert created.status_code == 201
    task_id = created.json()["id"]
    assert created.json()["status"] == "todo"
    assert (await client.get(f"/api/tasks/{task_id}", headers=alice)).status_code == 200
    for method in ("get", "patch", "delete"):
        kwargs = {"json": {"status": "done"}} if method == "patch" else {}
        response = await getattr(client, method)(f"/api/tasks/{task_id}", headers=bob, **kwargs)
        assert response.status_code == 404
    changed = await client.patch(f"/api/tasks/{task_id}", headers=alice, json={"status": "done"})
    assert changed.json()["status"] == "done"
    assert (await client.delete(f"/api/tasks/{task_id}", headers=alice)).status_code == 204
    assert (await client.get(f"/api/tasks/{task_id}", headers=alice)).status_code == 404


async def test_pagination_and_filter(users):
    client, _, alice, bob = users
    for i in range(3):
        await client.post("/api/tasks", headers=alice, json={"title": f"Task {i}"})
    first = (await client.get("/api/tasks?limit=2", headers=alice)).json()
    assert len(first["items"]) == 2
    assert first["next_offset"] == 2
    second = (await client.get("/api/tasks?limit=2&offset=2", headers=alice)).json()
    assert len(second["items"]) == 1
    assert second["next_offset"] is None
    assert set(t["id"] for t in first["items"]).isdisjoint(t["id"] for t in second["items"])
    assert (await client.get("/api/tasks?status=done", headers=alice)).json()["items"] == []
    assert (await client.get("/api/tasks", headers=bob)).json()["total"] == 0


@pytest.mark.parametrize(
    "url",
    [
        "/api/tasks?limit=0",
        "/api/tasks?limit=101",
        "/api/tasks?offset=-1",
        "/api/tasks?status=unknown",
    ],
)
async def test_invalid_pagination(users, url):
    client, _, alice, _ = users
    assert (await client.get(url, headers=alice)).status_code == 422


async def test_task_invalid_status_and_empty_title(users):
    client, _, alice, _ = users
    assert (await client.post("/api/tasks", headers=alice, json={"title": "  "})).status_code == 422
    task = (await client.post("/api/tasks", headers=alice, json={"title": "Task"})).json()
    response = await client.patch(
        f"/api/tasks/{task['id']}", headers=alice, json={"status": "unknown"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("client_kind", ["web", "mobile"])
async def test_shared_auth_contract_and_revocation(users, client_kind):
    client, _, alice, _ = users
    headers = {**alice, "X-Client": client_kind}
    profile = await client.get("/api/auth/me", headers=headers)
    assert profile.status_code == 200
    assert set(profile.json()) == {"id", "email", "birth_date"}
    assert (await client.post("/api/auth/logout", headers=headers)).status_code == 204
    assert (await client.get("/api/tasks", headers=headers)).status_code == 401


@pytest.mark.parametrize("header", [None, "Bearer invalid", "Basic abc", "Bearer"])
async def test_auth_rejects_missing_or_invalid_token(api, header):
    client, _ = api
    headers = {"Authorization": header} if header else {}
    response = await client.get("/api/tasks", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_expired_token(users):
    client, app, alice, _ = users
    async with app.state.db.connect() as db:
        await db.execute("UPDATE sessions SET expires_at = 0")
        await db.commit()
    assert (await client.get("/api/tasks", headers=alice)).status_code == 401


async def test_wrong_password(users):
    client, _, _, _ = users
    response = await client.post(
        "/api/auth/login", json={"email": "alice@example.com", "password": "wrong"}
    )
    assert response.status_code == 401


async def stock(app, quantity=5):
    async with app.state.db.connect() as db:
        await db.execute(
            "INSERT INTO products (id, name, price_cents, stock) VALUES (1, ?, ?, ?)",
            ("Notebook", 500000, quantity),
        )
        await db.commit()


async def test_order_creation_and_idempotency(users):
    client, app, alice, bob = users
    await stock(app)
    headers = {**alice, "Idempotency-Key": "order-001"}
    body = {"product_id": 1, "quantity": 2}
    first = await client.post("/api/orders", headers=headers, json=body)
    assert first.status_code == 201
    assert first.json()["total"] == "9000.00"
    second = await client.post("/api/orders", headers=headers, json=body)
    assert second.status_code == 200
    assert second.json() == first.json()
    changed = await client.post("/api/orders", headers=headers, json={**body, "quantity": 1})
    assert changed.status_code == 409
    assert (await client.get(f"/api/orders/{first.json()['id']}", headers=bob)).status_code == 404
    async with app.state.db.connect() as db:
        assert (await (await db.execute("SELECT stock FROM products WHERE id=1")).fetchone())[
            0
        ] == 3
        assert (await (await db.execute("SELECT count(*) FROM orders")).fetchone())[0] == 1


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"product_id": 1, "quantity": 6}, 409),
        ({"product_id": 999, "quantity": 1}, 404),
        ({"product_id": 1, "quantity": 0}, 422),
        ({"product_id": 1, "quantity": -1}, 422),
    ],
)
async def test_order_errors_do_not_change_database(users, body, status):
    client, app, alice, _ = users
    await stock(app)
    response = await client.post(
        "/api/orders", headers={**alice, "Idempotency-Key": "bad-order"}, json=body
    )
    assert response.status_code == status
    async with app.state.db.connect() as db:
        assert (await (await db.execute("SELECT stock FROM products")).fetchone())[0] == 5
        assert (await (await db.execute("SELECT count(*) FROM orders")).fetchone())[0] == 0


async def test_order_requires_idempotency_key(users):
    client, _, alice, _ = users
    response = await client.post(
        "/api/orders", headers=alice, json={"product_id": 1, "quantity": 1}
    )
    assert response.status_code == 422


async def test_concurrent_purchase_of_last_item(users):
    client, app, alice, bob = users
    await stock(app, 1)
    responses = await asyncio.gather(
        *[
            client.post(
                "/api/orders",
                headers={**owner, "Idempotency-Key": f"parallel-{i}"},
                json={"product_id": 1, "quantity": 1},
            )
            for i, owner in enumerate((alice, bob))
        ]
    )
    assert sorted(r.status_code for r in responses) == [201, 409]
    async with app.state.db.connect() as db:
        assert (await (await db.execute("SELECT stock FROM products")).fetchone())[0] == 0
        assert (await (await db.execute("SELECT count(*) FROM orders")).fetchone())[0] == 1


async def test_concurrent_identical_order_is_created_once(users):
    client, app, alice, _ = users
    await stock(app)
    responses = await asyncio.gather(
        *[
            client.post(
                "/api/orders",
                headers={**alice, "Idempotency-Key": "same-order"},
                json={"product_id": 1, "quantity": 1},
            )
            for _ in range(2)
        ]
    )
    assert sorted(r.status_code for r in responses) == [200, 201]
    assert responses[0].json() == responses[1].json()


async def test_database_failure_rolls_back_stock(users):
    client, app, alice, _ = users
    await stock(app)
    async with app.state.db.connect() as db:
        await db.execute("""CREATE TRIGGER fail_order BEFORE INSERT ON orders
                          BEGIN SELECT RAISE(ABORT, 'simulated DB failure'); END""")
        await db.commit()
    response = await client.post(
        "/api/orders",
        headers={**alice, "Idempotency-Key": "db-failure"},
        json={"product_id": 1, "quantity": 1},
    )
    assert response.status_code == 500
    assert "simulated" not in response.text
    async with app.state.db.connect() as db:
        assert (await (await db.execute("SELECT stock FROM products")).fetchone())[0] == 5
        assert (await (await db.execute("SELECT count(*) FROM orders")).fetchone())[0] == 0
