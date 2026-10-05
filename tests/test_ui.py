"""Real browser + real HTTP server; only network-failure scenarios intercept responses."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import pytest

pytestmark = pytest.mark.ui


@pytest.fixture
def ui_server(tmp_path):
    env = {**os.environ, "DATABASE_PATH": str(tmp_path / "ui.db")}
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "-m", "app.seed"], cwd=root, env=env, check=True, capture_output=True
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    with (tmp_path / "server.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=root,
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            for _ in range(100):
                if server.poll() is not None:
                    pytest.fail("UI server exited: " + (tmp_path / "server.log").read_text())
                try:
                    with urlopen(url + "/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                pytest.fail("UI server did not start")
            yield url
        finally:
            server.terminate()
            server.wait(timeout=10)


@pytest.fixture
def page(ui_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        context = browser.new_context(base_url=ui_server)
        page = context.new_page()
        page.set_default_timeout(5000)
        page.goto(ui_server)
        page.wait_for_load_state("networkidle")
        yield page
        context.close()
        browser.close()


def login(page, email="alice@example.com"):
    page.locator("#login-form [name=email]").fill(email)
    page.locator("#login-form [name=password]").fill("Demo-password-123")
    page.get_by_role("button", name="Войти", exact=True).click()
    page.locator("#workspace").wait_for(state="visible")


def add_task(page, title):
    page.get_by_label("Название задачи").fill(title)
    page.get_by_role("button", name="Добавить задачу").click()
    page.get_by_role("button", name=title, exact=True).wait_for()


def test_ui_form_required_and_invalid_fields(page):
    from playwright.sync_api import expect

    page.locator("#register-form button").click()
    expect(page.locator("#register-email-error")).to_contain_text("email")
    expect(page.locator("#register-birth-error")).to_contain_text("дату")
    page.locator("#register-form [name=email]").fill("not-an-email")
    page.locator("#register-form [name=birth_date]").fill("2999-01-01")
    page.locator("#register-form [name=password]").fill("short")
    page.locator("#register-form button").click()
    expect(page.locator("#register-birth-error")).to_contain_text("будущем")
    expect(page.locator("#register-password-error")).to_contain_text("10")


def test_ui_duplicate_email_and_correction(page):
    from playwright.sync_api import expect

    page.locator("#register-form [name=email]").fill("ALICE@example.com")
    page.locator("#register-form [name=birth_date]").fill("2000-01-01")
    page.locator("#register-form [name=password]").fill("Other-password-123")
    page.locator("#register-form button").click()
    expect(page.locator("#register-email-error")).to_contain_text("занят")
    expect(page.locator("#register-form [name=birth_date]")).to_have_value("2000-01-01")
    page.locator("#register-form [name=email]").fill("new@example.com")
    page.locator("#register-form button").click()
    expect(page.locator("#register-message")).to_contain_text("Аккаунт создан")


def test_ui_empty_create_details_and_delete(page):
    from playwright.sync_api import expect

    login(page)
    expect(page.locator("#list-message")).to_contain_text("Задач пока нет")
    add_task(page, "Learn transactions")
    page.get_by_role("button", name="Learn transactions", exact=True).click()
    expect(page.get_by_role("dialog")).to_be_visible()
    expect(page.locator("#detail-content")).to_contain_text("Learn transactions")
    page.get_by_role("button", name="Закрыть").click()
    page.get_by_role("button", name="Выполнить", exact=True).click()
    expect(page.locator("#tasks li")).to_contain_text("Готово")
    page.get_by_role("button", name="Удалить", exact=True).click()
    expect(page.locator("#list-message")).to_contain_text("Задач пока нет")


def test_ui_network_error_and_retry(page):
    from playwright.sync_api import expect

    page.route("**/api/tasks?*", lambda route: route.abort())
    login(page)
    expect(page.locator("#list-error")).to_be_visible()
    page.unroute("**/api/tasks?*")
    page.get_by_role("button", name="Повторить", exact=True).click()
    expect(page.locator("#list-message")).to_contain_text("Задач пока нет")


def test_ui_partial_result_keeps_first_page(page):
    from playwright.sync_api import expect

    login(page)
    # Use real HTTP to prepare more than one page, without going through UI six times.
    login_response = page.request.post(
        "/api/auth/login", data={"email": "alice@example.com", "password": "Demo-password-123"}
    )
    token = login_response.json()["access_token"]
    for i in range(6):
        response = page.request.post(
            "/api/tasks",
            headers={"Authorization": f"Bearer {token}"},
            data={"title": f"Page task {i}"},
        )
        assert response.status == 201
    page.get_by_role("button", name="Обновить", exact=True).click()
    expect(page.locator("#tasks li")).to_have_count(5)
    page.route("**/api/tasks?*offset=5*", lambda route: route.abort())
    page.get_by_role("button", name="Загрузить ещё", exact=True).click()
    expect(page.locator("#list-error")).to_contain_text("часть")
    expect(page.locator("#tasks li")).to_have_count(5)
    page.unroute("**/api/tasks?*offset=5*")
    page.get_by_role("button", name="Повторить", exact=True).click()
    expect(page.locator("#tasks li")).to_have_count(6)


def test_ui_loading_and_fast_filter_change_ignore_old_response(page):
    from playwright.sync_api import expect

    login(page)
    add_task(page, "Old filter task")
    # Delay the network promise itself to verify the generation check even when
    # an old response completes despite cancellation.
    page.evaluate("""() => {
      const original = window.fetch;
      window.fetch = async (...args) => {
        const response = await original(...args);
        if (String(args[0]).includes('status=todo')) {
          const body = await response.json();
          await new Promise(resolve => { window.releaseOldRequest = resolve; });
          return {
            ok: response.ok, status: response.status,
            json: async () => {
            window.oldBodyConsumed = true;
            return body;
            }
          };
        }
        return response;
      };
    }""")
    page.get_by_label("Статус задач").select_option("todo")
    expect(page.locator("#list-message")).to_contain_text("Загрузка")
    page.wait_for_function("Boolean(window.releaseOldRequest)")
    page.get_by_label("Статус задач").select_option("done")
    expect(page.locator("#list-message")).to_contain_text("Задач пока нет")
    page.evaluate("window.releaseOldRequest()")
    page.wait_for_function("Boolean(window.oldBodyConsumed)")
    expect(page.locator("#tasks li")).to_have_count(0)


def test_ui_late_logout_response_does_not_clear_new_session(page):
    from playwright.sync_api import expect

    login(page)
    page.evaluate("""() => {
      const original = window.fetch;
      window.fetch = async (...args) => {
        const response = await original(...args);
        if (String(args[0]).endsWith('/api/auth/logout')) {
          await new Promise(resolve => { window.releaseLogout = resolve; });
          window.logoutDelivered = true;
        }
        return response;
      };
    }""")
    page.get_by_role("button", name="Выйти", exact=True).click()
    page.wait_for_function("Boolean(window.releaseLogout)")
    # Local logout must be immediate, even while the old server response is pending.
    expect(page.locator("#auth-panels")).to_be_visible()
    login(page, "bob@example.com")
    page.evaluate("window.releaseLogout()")
    page.wait_for_function("Boolean(window.logoutDelivered)")
    expect(page.locator("#workspace")).to_be_visible()
    expect(page.locator("#account-email")).to_have_text("bob@example.com")
    add_task(page, "Bob session remains active")


def test_ui_narrow_and_wide_layout(page):
    from playwright.sync_api import expect

    login(page)
    add_task(page, "Responsive task")
    for width, height in ((390, 844), (844, 390)):
        page.set_viewport_size({"width": width, "height": height})
        expect(page.get_by_role("button", name="Responsive task", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
