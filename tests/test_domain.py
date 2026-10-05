from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("0", "0.00"),
        ("9999.99", "9999.99"),
        ("10000", "9000.00"),
        ("10000.01", "9000.01"),
        ("10000.05", "9000.05"),
        ("20000", "18000.00"),
    ],
)
def test_discount_boundaries(amount, expected):
    from app.discount import apply_discount

    assert apply_discount(Decimal(amount)) == Decimal(expected)


@pytest.mark.parametrize("amount", ["-0.01", "NaN", "Infinity", "1.001"])
def test_discount_rejects_invalid_money(amount):
    from app.discount import apply_discount

    with pytest.raises(ValueError):
        apply_discount(Decimal(amount))


def test_custom_discount_threshold():
    from app.discount import apply_discount

    assert apply_discount(Decimal("500"), Decimal("500"), Decimal("0.20")) == Decimal("400")


@pytest.mark.parametrize(
    ("threshold", "rate"),
    [("-1", ".1"), ("NaN", ".1"), ("100", "1.1"), ("100", "-.1"), ("100", "NaN")],
)
def test_discount_rejects_invalid_configuration(threshold, rate):
    from app.discount import apply_discount

    with pytest.raises(ValueError):
        apply_discount(Decimal("500"), Decimal(threshold), Decimal(rate))


def test_registration_normalizes_email():
    from app.schemas import Registration

    user = Registration(
        email="  ALICE@EXAMPLE.COM  ", birth_date="2000-01-01", password="Test-password-123"
    )
    assert user.email == "alice@example.com"


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"email": "bad", "birth_date": "2000-01-01", "password": "Test-password-123"},
        {"email": "a@example.com", "birth_date": "2020-02-30", "password": "Test-password-123"},
        {
            "email": "a@example.com",
            "birth_date": str(date.today() + timedelta(days=1)),
            "password": "Test-password-123",
        },
        {"email": "a@example.com", "birth_date": "2000-01-01", "password": "short"},
        {
            "email": "a@example.com",
            "birth_date": "2000-01-01",
            "password": "Test-password-123",
            "is_admin": True,
        },
    ],
)
def test_registration_rejects_invalid_fields(values):
    from app.schemas import Registration

    with pytest.raises(ValidationError):
        Registration(**values)
