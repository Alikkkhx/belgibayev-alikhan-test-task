# 11. API списка задач

Базовый URL: `http://127.0.0.1:8000`. Формат — JSON. Полный контракт доступен в `/docs` и `/openapi.json`.

## Получить токен

После `python -m app.seed`:

```http
POST /api/auth/login
Content-Type: application/json

{"email":"alice@example.com","password":"Demo-password-123"}
```

```json
{"access_token":"<случайный токен>","token_type":"bearer","expires_in":1800}
```

Далее во всех запросах к задачам отправлять `Authorization: Bearer <токен>`.
В Swagger вставить только токен в **Authorize**. В БД хранится SHA-256 токена,
сам токен выдаётся при входе. Выход `POST /api/auth/logout` отзывает текущую сессию.

## Методы

| Метод и путь | Назначение | Успех |
|---|---|---|
| `POST /api/tasks` | Создать задачу | `201 Created` |
| `GET /api/tasks` | Получить свои задачи | `200 OK` |
| `GET /api/tasks/{id}` | Получить одну свою задачу | `200 OK` |
| `PATCH /api/tasks/{id}` | Изменить статус | `200 OK` |
| `DELETE /api/tasks/{id}` | Удалить задачу | `204 No Content`, без тела |

`title` — строка от 1 до 200 символов после удаления пробелов по краям.
Статусы: `todo`, `in_progress`, `done`. Новая задача получает `todo`.
Все переходы между этими статусами разрешены: специальных правил в условии нет.
`owner_id` берётся из сессии, передать его в JSON нельзя.

### Создание

```http
POST /api/tasks
Authorization: Bearer <токен>
Content-Type: application/json

{"title":"Проверить API"}
```

Ответ `201`:

```json
{"id":1,"title":"Проверить API","status":"todo","created_at":"2026-10-06T10:00:00Z"}
```

Время в примерах условное. Реальное `created_at` формируется сервером в UTC.

### Просмотр и пагинация

```http
GET /api/tasks?limit=2&offset=0&status=todo
Authorization: Bearer <токен>
```

```json
{
  "items":[
    {"id":1,"title":"Проверить API","status":"todo","created_at":"2026-10-06T10:00:00Z"},
    {"id":2,"title":"Написать тест","status":"todo","created_at":"2026-10-06T10:01:00Z"}
  ],
  "total":3,
  "limit":2,
  "offset":0,
  "next_offset":2
}
```

Следующий запрос: `GET /api/tasks?limit=2&offset=2&status=todo`.
На последней странице `next_offset` равен `null`.
По умолчанию `limit=20`, допустимы 1–100; `offset >= 0`. Фильтр статуса необязателен.
`total` учитывает владельца и фильтр. Порядок — возрастающий `id`.
Пустой список — `200` с `items: []`, `total: 0`, `next_offset: null`.

Offset прост и достаточен для небольшого учебного списка. При удалении/добавлении записей
между запросами страницы могут смещаться; стабильная сортировка не устраняет этот эффект.
Для большой изменяемой ленты я бы использовал cursor по `(created_at, id)`.

Просмотр одной задачи: `GET /api/tasks/1` → тот же объект, без обёртки `items`.

### Изменение статуса

```http
PATCH /api/tasks/1
Authorization: Bearer <токен>
Content-Type: application/json

{"status":"done"}
```

Ответ `200`:

```json
{"id":1,"title":"Проверить API","status":"done","created_at":"2026-10-06T10:00:00Z"}
```

### Удаление

`DELETE /api/tasks/1` с bearer-токеном → `204`, без тела.
Повторное удаление → `404`.

## Ошибки

| Код | Когда |
|---|---|
| `401` | Нет корректной активной сессии; также `WWW-Authenticate: Bearer` |
| `404` | Задача отсутствует или принадлежит другому пользователю |
| `422` | Пустое/длинное название, неизвестный статус, неверная пагинация или лишнее поле |
| `500` | Ошибка БД; внутренние сведения в ответ не включаются |
| `503` | БД занята дольше времени ожидания; можно повторить позже |

Чужая и отсутствующая задача обе возвращают `404`, чтобы не раскрывать существование чужой записи.

Пример запроса с `{"title":""}` → `422`:

```json
{
  "error": {
    "code":"validation_error",
    "message":"Проверьте поля формы",
    "fields":{"title":"String should have at least 1 character"},
    "request_id":"<ID запроса>"
  }
}
```

У ошибок без привязки к полям `fields` — пустой объект. Текст технических сообщений
валидации может меняться с версией Pydantic; клиент использует поля и код ошибки.
Каждый ответ содержит `X-Request-ID` для поиска запроса в журнале.

## Остальные endpoint

| Метод и путь | Ввод / результат |
|---|---|
| `POST /api/auth/register` | email, birth_date, password → профиль, `201`; занятый email → `409` |
| `POST /api/auth/login` | email, password → bearer-токен |
| `GET /api/auth/me` | Активная сессия → id, email, birth_date |
| `POST /api/auth/logout` | Отозвать текущую сессию, `204` |
| `GET /api/products` | Авторизованный пользователь → учебный каталог с остатками |
| `POST /api/orders` | product_id, quantity; обязательный заголовок Idempotency-Key |
| `GET /api/orders/{id}` | Только свой заказ |

Пример заказа:

```http
POST /api/orders
Authorization: Bearer <токен>
Idempotency-Key: order-example-001
Content-Type: application/json

{"product_id":1,"quantity":2}
```

Ответ `201`:

```json
{"id":1,"product_id":1,"quantity":2,"total":"9000.00","created_at":"2026-10-06T10:00:00Z"}
```

Повтор того же тела и ключа для этого пользователя → `200`, тот же заказ.
Тот же ключ с другим телом → `409 idempotency_conflict`.
Ключ ограничен 128 символами, разрешены латинские буквы, цифры, `_` и `-`.
Количество — целое число 1–1000. Цену и итог определяет сервер.
Отсутствующий товар → `404`, нехватка остатка → `409`, ошибка ввода → `422`.
Один заказ в примере содержит один вид товара; корзина из нескольких позиций не требуется условием.
