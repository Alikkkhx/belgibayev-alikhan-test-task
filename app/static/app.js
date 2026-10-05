import {api, setToken} from "./api.js";
import {TaskList} from "./task-list.js";

const $ = (selector) => document.querySelector(selector);
const statusNames = {todo: "Нужно сделать", in_progress: "В работе", done: "Готово"};
let sessionGeneration = 0;
const dateToday = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
};
$("#register-birth").max = dateToday();

function formValues(form) { return Object.fromEntries(new FormData(form)); }
function text(selector, value) { $(selector).textContent = value; }
function formBusy(form, busy) { form.querySelector("button[type=submit]").disabled = busy; }

const fields = {
  email: ["#register-email", "#register-email-error"],
  birth_date: ["#register-birth", "#register-birth-error"],
  password: ["#register-password", "#register-password-error"],
};

function showFieldErrors(errors) {
  let first = null;
  for (const [name, [input, message]] of Object.entries(fields)) {
    text(message, errors[name] || "");
    $(input).setAttribute("aria-invalid", errors[name] ? "true" : "false");
    if (errors[name] && !first) first = $(input);
  }
  first?.focus();
}

$("#register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = formValues(form);
  const errors = {};
  text("#register-message", "");
  if (!values.email.trim() || !$("#register-email").validity.valid) errors.email = "Укажите корректный email";
  if (!values.birth_date) errors.birth_date = "Укажите дату рождения";
  else if (values.birth_date > dateToday()) errors.birth_date = "Дата не может быть в будущем";
  else if (values.birth_date < "1900-01-01") errors.birth_date = "Допустимы даты с 1900 года";
  if (values.password.length < 10 || values.password.length > 128) errors.password = "От 10 до 128 символов";
  showFieldErrors(errors);
  if (Object.keys(errors).length) return;
  formBusy(form, true);
  try {
    await api("/api/auth/register", {method: "POST", body: JSON.stringify(values)});
    $("#login-email").value = values.email.trim();
    $("#register-password").value = "";
    text("#register-message", "Аккаунт создан. Теперь можно войти.");
  } catch (error) {
    showFieldErrors(error.fields || {});
    text("#register-message", error.message || "Не удалось создать аккаунт");
  } finally { formBusy(form, false); }
});

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const generation = ++sessionGeneration;
  formBusy(form, true);
  text("#login-message", "Входим…");
  try {
    const values = formValues(form);
    const session = await api("/api/auth/login", {method: "POST", body: JSON.stringify(values)});
    if (generation !== sessionGeneration) return;
    setToken(session.access_token);
    $("#login-password").value = "";
    $("#auth-panels").hidden = true;
    $("#workspace").hidden = false;
    $("#logout").disabled = false;
    text("#account-email", values.email.trim());
    text("#login-message", "");
    await list.setFilter($("#status-filter").value);
  } catch (error) { if (generation === sessionGeneration) text("#login-message", error.message); }
  finally { formBusy(form, false); }
});

async function logout() {
  if ($("#logout").disabled) return;
  $("#logout").disabled = true;
  const generation = ++sessionGeneration;
  // Capture the old token in the request, then immediately clear local state.
  const revocation = api("/api/auth/logout", {method: "POST"});
  list.dispose();
  closeDetails();
  setToken(null);
  $("#workspace").hidden = true;
  $("#auth-panels").hidden = false;
  text("#task-message", "");
  text("#login-message", "");
  try { await revocation; }
  catch (error) {
    if (generation === sessionGeneration) text("#login-message", error.message);
  }
}
$("#logout").addEventListener("click", logout);

function render(state) {
  $("#task-results").setAttribute("aria-busy", state.phase === "loading" ? "true" : "false");
  text("#list-message", state.phase === "loading" ? "Загрузка…" :
    state.phase === "empty" ? "Задач пока нет. Добавьте задачу или измените фильтр." : "");
  $("#list-error").hidden = !["error", "partial"].includes(state.phase);
  text("#list-error-text", state.phase === "partial"
    ? `Показана только часть задач. ${state.message}. Попробуйте загрузить остальные.`
    : `${state.message}. Попробуйте ещё раз. Если сессия истекла, войдите повторно.`);
  $("#load-more").hidden = state.nextOffset === null || state.phase !== "success";
  $("#refresh").disabled = state.phase === "loading";
  const nodes = state.items.map((task) => {
    const row = document.createElement("li");
    const title = document.createElement("button");
    title.type = "button";
    title.className = "task-name";
    title.textContent = task.title;
    title.addEventListener("click", () => openDetails(task.id));
    const status = document.createElement("span");
    status.className = "task-meta";
    status.textContent = statusNames[task.status];
    const actions = document.createElement("div");
    actions.className = "task-actions";
    for (const [label, method, body] of [
      [task.status === "done" ? "Вернуть" : "Выполнить", "PATCH", {status: task.status === "done" ? "todo" : "done"}],
      ["Удалить", "DELETE", null],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary";
      button.textContent = label;
      button.disabled = state.phase === "loading";
      button.addEventListener("click", async () => {
        const generation = sessionGeneration;
        button.disabled = true;
        try {
          await api(`/api/tasks/${task.id}`, {method, ...(body ? {body: JSON.stringify(body)} : {})});
          if (generation !== sessionGeneration) return;
          await list.load();
        } catch (error) { if (generation === sessionGeneration) text("#task-message", error.message); }
        finally { button.disabled = false; }
      });
      actions.append(button);
    }
    row.append(title, status, actions);
    return row;
  });
  $("#tasks").replaceChildren(...nodes);
}

const list = new TaskList(render);
$("#status-filter").addEventListener("change", (event) => list.setFilter(event.target.value));
$("#refresh").addEventListener("click", () => list.load());
$("#load-more").addEventListener("click", () => list.load(true));
$("#retry").addEventListener("click", () => list.retry());

$("#task-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const generation = sessionGeneration;
  formBusy(form, true);
  text("#task-message", "");
  try {
    await api("/api/tasks", {method: "POST", body: JSON.stringify(formValues(form))});
    if (generation !== sessionGeneration) return;
    form.reset();
    await list.load();
  } catch (error) {
    if (generation === sessionGeneration) text("#task-message", error.fields?.title || error.message);
  }
  finally { formBusy(form, false); }
});

let detailController = null;
async function openDetails(id) {
  detailController?.abort();
  const controller = new AbortController();
  detailController = controller;
  text("#detail-content", "Загрузка…");
  $("#task-detail").showModal();
  try {
    const task = await api(`/api/tasks/${id}`, {signal: controller.signal});
    if (controller !== detailController || !$("#task-detail").open) return;
    text("#detail-content", `${task.title} · ${statusNames[task.status]} · №${task.id}`);
  } catch (error) {
    if (controller === detailController && error.name !== "AbortError") text("#detail-content", error.message);
  }
}
function closeDetails() {
  detailController?.abort();
  detailController = null;
  $("#task-detail").close();
}
$("#close-detail").addEventListener("click", closeDetails);
$("#task-detail").addEventListener("cancel", () => { detailController?.abort(); detailController = null; });
window.addEventListener("pagehide", () => { list.dispose(); detailController?.abort(); });
