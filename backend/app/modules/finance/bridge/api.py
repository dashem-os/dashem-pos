"""The bridge's own door: take a command, say it arrived, say what happened.

These routes carry no user session and pass through no user permission. The
bridge authenticates with the credential issued at pairing, sent in a header,
and the tenant and unit come from the terminal it opens (§3.4).

Waiting is not holding. The long poll never keeps a transaction open or a
connection checked out while it waits: every attempt opens a session, commits
and closes it, and the wait itself is an `await` with nothing in hand (§3.12).
Above a ceiling of waiters per process the route answers at once and asks the
bridge to come back, degrading to short polling instead of taking the API down.
"""

import asyncio
import time
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.database import get_session
from app.models.provider import ProviderTransactionStatusEnum
from app.modules.finance.bridge import credentials, delivery
from app.modules.finance.bridge.models import (
    BridgeCommandClassEnum, BridgeCommandDeliveryStatusEnum, BridgeCommandTypeEnum,
)
from app.services import provider_service


router = APIRouter()

WAIT_SECONDS = 25
POLL_SECONDS = 1.0
MAX_WAITERS = 50
_waiting = 0


class BridgeCommandDTO(BaseModel):
    id: uuid.UUID
    command_type: BridgeCommandTypeEnum
    command_class: BridgeCommandClassEnum
    sequence: int
    provider_transaction_id: uuid.UUID
    installation_epoch: int
    attempts: int
    lease_expires_at: datetime
    correlation_id: str
    payload: dict


class BridgeCommandStateDTO(BaseModel):
    id: uuid.UUID
    delivery_status: BridgeCommandDeliveryStatusEnum
    closed_reason: Optional[str] = None


class BridgeCommandResultDTO(BaseModel):
    """What the provider answered. `FAILED` means the provider refused.

    A bridge that does not know whether the charge went through answers
    `UNKNOWN`, never `FAILED`: a refusal frees the pinpad, and not knowing must
    not.
    """

    status: ProviderTransactionStatusEnum
    external_transaction_id: Optional[str] = Field(default=None, max_length=160)
    nsu: Optional[str] = Field(default=None, max_length=80)
    authorization_code: Optional[str] = Field(default=None, max_length=80)
    acquirer: Optional[str] = Field(default=None, max_length=80)
    card_brand: Optional[str] = Field(default=None, max_length=40)
    failure_code: Optional[str] = Field(default=None, max_length=80)
    failure_reason: Optional[str] = Field(default=None, max_length=300)
    refunded_amount: Optional[Decimal] = Field(default=None, ge=0)


class BridgeCommandOutcomeDTO(BaseModel):
    command: BridgeCommandStateDTO
    transaction_status: ProviderTransactionStatusEnum


def _credential(value: str = Header(alias="X-Bridge-Credential", min_length=8, max_length=200)) -> str:
    return value


@router.get(
    "/terminals/{terminal_id}/commands",
    response_model=BridgeCommandDTO,
    responses={204: {"description": "Nada a entregar dentro da espera; volte a perguntar."}},
)
async def next_bridge_command(
    terminal_id: uuid.UUID, request: Request,
    wait: int = Query(default=WAIT_SECONDS, ge=0, le=WAIT_SECONDS),
    credential: str = Depends(_credential),
):
    global _waiting
    scope = await run_in_threadpool(credentials.authenticate, terminal_id, credential)
    await run_in_threadpool(delivery.touch, scope)
    saturated = _waiting >= MAX_WAITERS
    deadline = time.monotonic() + (0 if saturated else wait)
    _waiting += 1
    try:
        while True:
            body = await run_in_threadpool(delivery.claim, scope)
            if body is not None:
                return body
            if time.monotonic() >= deadline or await request.is_disconnected():
                return Response(status_code=204, headers={"Retry-After": "2" if saturated else "0"})
            await asyncio.sleep(POLL_SECONDS)
    finally:
        _waiting -= 1


@router.post("/terminals/{terminal_id}/commands/{command_id}/ack", response_model=BridgeCommandStateDTO)
def ack_bridge_command(
    terminal_id: uuid.UUID, command_id: uuid.UUID,
    credential: str = Depends(_credential), session: Session = Depends(get_session),
):
    scope = credentials.authenticate(terminal_id, credential)
    return delivery.ack(session, scope, command_id)


@router.post("/terminals/{terminal_id}/commands/{command_id}/result", response_model=BridgeCommandOutcomeDTO)
def report_bridge_command_result(
    terminal_id: uuid.UUID, command_id: uuid.UUID, data: BridgeCommandResultDTO,
    credential: str = Depends(_credential), session: Session = Depends(get_session),
):
    scope = credentials.authenticate(terminal_id, credential)
    return provider_service.report_command_result(
        session, scope, command_id, status_value=data.status,
        external_transaction_id=data.external_transaction_id, nsu=data.nsu,
        authorization_code=data.authorization_code, acquirer=data.acquirer,
        card_brand=data.card_brand, failure_code=data.failure_code,
        failure_reason=data.failure_reason, refunded_amount=data.refunded_amount,
    )
