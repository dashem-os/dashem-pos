"""Opening and closing a shift belong to whoever is holding it.

A management session authorises the infrastructure: it creates the terminal,
configures the unit and opens the point of sale for validation. The shift itself
is a financial fact attributed to an operator, so it requires the operational
session created by code and personal PIN on the authorised terminal.

Without this, a manager could open or close a drawer under an identity that
never assumed the shift, and productivity and closing figures would answer to
nobody.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.core.context import TenantContext
from app.core.database import engine
from app.services import cash_service


def _management_context() -> TenantContext:
    """An authenticated manager on the POS surface, with no shift assumed."""
    return TenantContext(
        tenant_id=uuid.uuid4(),
        store_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        permissions=("cash.open", "cash.close", "management.read"),
        auth_subject="authenticated-manager",
    )


def _operational_context() -> TenantContext:
    """A collaborator who assumed the shift on an authorised terminal."""
    return TenantContext(
        tenant_id=uuid.uuid4(),
        store_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        permissions=("cash.open", "cash.close"),
        auth_subject="authenticated-operator",
        auth_provider="operational",
        operational_session_id=uuid.uuid4(),
    )


def test_manager_cannot_open_a_shift_without_assuming_it():
    with Session(engine) as session:
        with pytest.raises(HTTPException) as raised:
            cash_service.open_cash_session(
                session, _management_context(),
                store_id=uuid.uuid4(), register_id=uuid.uuid4(),
                operator_id=uuid.uuid4(), opening_balance=Decimal("100.00"),
            )
    assert raised.value.status_code == 403
    assert "sessão operacional" in raised.value.detail


def test_manager_cannot_close_a_shift_without_assuming_it():
    with Session(engine) as session:
        with pytest.raises(HTTPException) as raised:
            cash_service.begin_cash_close(
                session, _management_context(), uuid.uuid4(),
                operator_id=uuid.uuid4(), expected_version=None, blind_count=False,
            )
    assert raised.value.status_code == 403
    assert "sessão operacional" in raised.value.detail


def test_the_refusal_is_about_the_shift_and_not_about_the_register():
    """An operational session gets past the authority check and fails later.

    The context carries a shift, so the guard lets it through. The actor matches
    the authenticated identity, so Gate A lets it through too. The request then
    stops on the register that does not exist, which is a different rule.
    """
    context = _operational_context()
    with Session(engine) as session:
        with pytest.raises(HTTPException) as raised:
            cash_service.open_cash_session(
                session, context,
                store_id=context.store_id, register_id=uuid.uuid4(),
                operator_id=context.user_id, opening_balance=Decimal("100.00"),
            )
    assert raised.value.status_code == 400
    assert "sessão operacional" not in str(raised.value.detail)
