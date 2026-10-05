import importlib.util

import pytest


def pytest_addoption(parser):
    parser.addoption("--ui", action="store_true", help="Run Chromium UI tests")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--ui"):
        for item in items:
            if "ui" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Pass --ui to run browser tests"))


@pytest.fixture
async def api(tmp_path):
    assert importlib.util.find_spec("app") is not None, "API implementation is missing"
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    app = create_app(tmp_path / "test.db")
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, app


@pytest.fixture
async def users(api):
    client, app = api
    result = []
    for name in ("alice", "bob"):
        body = {
            "email": f"{name}@example.com",
            "birth_date": "2000-01-01",
            "password": "Test-password-123",
        }
        response = await client.post("/api/auth/register", json=body)
        assert response.status_code == 201
        login = await client.post(
            "/api/auth/login", json={"email": body["email"], "password": body["password"]}
        )
        assert login.status_code == 200
        result.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    return client, app, result[0], result[1]
