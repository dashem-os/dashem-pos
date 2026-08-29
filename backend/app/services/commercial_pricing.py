from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import HTTPException


MONEY = Decimal("0.01")
RATE = Decimal("0.0001")


def calculate_discount(
    *,
    gross_amount: Decimal,
    discount_type: Optional[str],
    discount_value: Decimal,
    starts_on: Optional[date],
    ends_on: Optional[date],
    effective_on: date,
) -> Decimal:
    gross = Decimal(gross_amount).quantize(MONEY, rounding=ROUND_HALF_UP)
    value = Decimal(discount_value).quantize(RATE, rounding=ROUND_HALF_UP)
    if discount_type is None or value == 0:
        return Decimal("0.00")
    if starts_on and effective_on < starts_on:
        return Decimal("0.00")
    if ends_on and effective_on > ends_on:
        return Decimal("0.00")
    if discount_type == "PERCENTAGE":
        if value > Decimal("100"):
            raise HTTPException(status_code=422, detail="O desconto percentual não pode superar 100%.")
        amount = gross * value / Decimal("100")
    elif discount_type == "FIXED":
        amount = value
    else:
        raise HTTPException(status_code=422, detail="Tipo de desconto contratual inválido.")
    amount = amount.quantize(MONEY, rounding=ROUND_HALF_UP)
    if amount > gross:
        raise HTTPException(status_code=422, detail="O desconto não pode superar o valor-base contratado.")
    return amount


def validate_discount_dates(
    *, starts_on: Optional[date], ends_on: Optional[date], review_on: Optional[date]
) -> None:
    if starts_on and ends_on and ends_on < starts_on:
        raise HTTPException(status_code=422, detail="O fim do desconto não pode anteceder o início.")
    if starts_on and review_on and review_on < starts_on:
        raise HTTPException(status_code=422, detail="A revisão do desconto não pode anteceder o início.")


def subscription_amounts(subscription, *, effective_on: date) -> tuple[Decimal, Decimal, Decimal]:
    gross = Decimal(subscription.gross_monthly_amount).quantize(MONEY)
    discount = calculate_discount(
        gross_amount=gross,
        discount_type=subscription.discount_type,
        discount_value=subscription.discount_value,
        starts_on=subscription.discount_starts_on,
        ends_on=subscription.discount_ends_on,
        effective_on=effective_on,
    )
    return gross, discount, (gross - discount).quantize(MONEY)
