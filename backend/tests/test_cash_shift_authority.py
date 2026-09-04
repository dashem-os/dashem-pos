"""A shift is a financial fact and must answer to a named person.

Who may open or close one is the permission matrix: `cash.open` and `cash.close`,
enforced per route. Whose name goes on it is `resolve_actor`, which only accepts
the authenticated principal. Nothing in between asks which kind of session is
holding the shift.

An earlier version of this module asserted the opposite — that opening required
an operational session created by code and PIN. That rule contradicted the
matrix, which has granted `cash.open` to OWNER, TENANT_OWNER, ADMIN and MANAGER
since migration 017, and it made a merchant working alone invent a second
identity of herself in order to sell her own goods. Decision of the SaaS owner on
4 September 2026: the manager opens and closes the till from their own
authenticated web session; on a shared counter terminal the code and PIN remain
what identifies the person, because that surface only ever offers the
operational gate.
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
    """An authenticated manager validating the POS from their own browser."""
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


def _anonymous_context() -> TenantContext:
    """A context carrying no principal at all."""
    return TenantContext(
        tenant_id=uuid.uuid4(),
        store_id=uuid.uuid4(),
        user_id=None,
        permissions=("cash.open", "cash.close"),
        auth_subject="unresolved",
    )


def test_a_manager_opens_the_till_from_their_own_session():
    """The guard lets the manager through; the request stops on the register.

    Reaching a "register does not exist" error is the proof: the authority check
    was passed, and what refused afterwards is a different rule entirely.
    """
    context = _management_context()
    with Session(engine) as session:
        with pytest.raises(HTTPException) as raised:
            cash_service.open_cash_session(
                session, context,
                store_id=context.store_id, register_id=uuid.uuid4(),
                operator_id=context.user_id, opening_balance=Decimal("100.00"),
            )
    assert raised.value.status_code == 400
    assert "identidade autenticada" not in str(raised.value.detail)


def test_a_manager_closes_the_till_from_their_own_session():
    context = _management_context()
    with Session(engine) as session:
        with pytest.raises(HTTPException) as raised:
            cash_service.begin_cash_close(
                session, context, uuid.uuid4(),
                operator_id=context.user_id, expected_version=None, blind_count=False,
            )
    # It stops on the cash session that does not exist, not on the authority.
    assert raised.value.status_code == 404


def test_an_operational_shift_opens_the_till_the_same_way():
    context = _operational_context()
    with Session(engine) as session:
        with pytest.raises(HTTPException) as raised:
            cash_service.open_cash_session(
                session, context,
                store_id=context.store_id, register_id=uuid.uuid4(),
                operator_id=context.user_id, opening_balance=Decimal("100.00"),
            )
    assert raised.value.status_code == 400


def test_a_shift_is_never_opened_without_a_named_person():
    """Whatever else changes, a till may not answer to nobody."""
    with Session(engine) as session:
        with pytest.raises(HTTPException) as raised:
            cash_service.open_cash_session(
                session, _anonymous_context(),
                store_id=uuid.uuid4(), register_id=uuid.uuid4(),
                operator_id=uuid.uuid4(), opening_balance=Decimal("100.00"),
            )
    assert raised.value.status_code == 403
    assert "identidade autenticada" in raised.value.detail


def test_nobody_opens_a_shift_under_someone_elses_name():
    """Gate A survives the change: the actor is the authenticated principal."""
    context = _management_context()
    with Session(engine) as session:
        with pytest.raises(HTTPException) as raised:
            cash_service.open_cash_session(
                session, context,
                store_id=context.store_id, register_id=uuid.uuid4(),
                operator_id=uuid.uuid4(), opening_balance=Decimal("100.00"),
            )
    assert raised.value.status_code == 403
    assert "Ator não corresponde" in raised.value.detail
