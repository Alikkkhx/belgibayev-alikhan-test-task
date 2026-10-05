from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(InputModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().casefold() if isinstance(value, str) else value


class Registration(Login):
    password: Annotated[str, Field(min_length=10, max_length=128)]
    birth_date: date

    @field_validator("birth_date", mode="before")
    @classmethod
    def require_date(cls, value: object) -> object:
        if isinstance(value, datetime) or not isinstance(value, (str, date)):
            raise ValueError("Используйте дату в формате YYYY-MM-DD")
        if isinstance(value, str):
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError as exc:
                raise ValueError("Используйте реальную дату в формате YYYY-MM-DD") from exc
        return value

    @field_validator("birth_date")
    @classmethod
    def validate_birth_date(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("Дата рождения не может быть в будущем")
        if value < date(1900, 1, 1):
            raise ValueError("В учебной форме допустимы даты с 1900 года")
        return value


class UserOut(BaseModel):
    id: int
    email: str
    birth_date: date


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TaskStatus(StrEnum):
    todo = "todo"
    in_progress = "in_progress"
    done = "done"


class TaskCreate(InputModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class TaskUpdate(InputModel):
    status: TaskStatus


class TaskOut(BaseModel):
    id: int
    title: str
    status: TaskStatus
    created_at: datetime


class TaskPage(BaseModel):
    items: list[TaskOut]
    total: int
    limit: int
    offset: int
    next_offset: int | None


class OrderCreate(InputModel):
    product_id: Annotated[int, Field(strict=True, gt=0)]
    quantity: Annotated[int, Field(strict=True, ge=1, le=1000)]


class OrderOut(BaseModel):
    id: int
    product_id: int
    quantity: int
    total: str
    created_at: datetime


class ProductOut(BaseModel):
    id: int
    name: str
    price_cents: int
    stock: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: dict[str, str] = Field(default_factory=dict)
    request_id: str


class ErrorOut(BaseModel):
    error: ErrorDetail
