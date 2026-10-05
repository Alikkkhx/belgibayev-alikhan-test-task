from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def apply_discount(
    amount: Decimal,
    threshold: Decimal = Decimal("10000.00"),
    rate: Decimal = Decimal("0.10"),
) -> Decimal:
    """Discount applies at the inclusive threshold; money has two decimal places."""
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(CENT):
        raise ValueError("Amount must be non-negative money with at most two decimal places")
    if not threshold.is_finite() or threshold < 0:
        raise ValueError("Threshold must be finite and non-negative")
    if not rate.is_finite() or not 0 <= rate <= 1:
        raise ValueError("Rate must be between 0 and 1")
    result = amount * (1 - rate) if amount >= threshold else amount
    return result.quantize(CENT, rounding=ROUND_HALF_UP)
