"""The routes the channels module owns.

`POST /channels/ingress/{provider_code}` carries no user session and passes
through no user permission: the caller is the channel, and it proves itself by
the signature its adapter checks. The response says what happened to each event
so the channel can stop resending what was kept; applying them to orders runs
right after the response (trigger (a) of the inbox).

`POST /channels/inbox/{event_id}/resume` is a person retaking a quarantined or
reviewed event. It is a `/channels` mutation, so the route map requires
`channel.manage`; it never moves a retention deadline.

`GET /channels/outbound` lists notices to the channel — no payload, no person —
and `POST /channels/outbound/{message_id}/resend` sends a dead letter again under
`channel.manage`.

`GET /channels/deadlines` counts orders still waiting for their clocks and
records past their deadline: how many and since when, never what they hold.
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context, resolve_actor
from app.core.database import get_session
from app.models.channel_hub import ChannelInboxStatusEnum, ChannelOutboundStatusEnum
from app.modules.channels import inbox, ingress, outbound, retention


router = APIRouter()


class IngressEventOutcomeDTO(BaseModel):
    provider_event_id: str
    outcome: str


class IngressResponseDTO(BaseModel):
    events: list[IngressEventOutcomeDTO]


class ResumeDTO(BaseModel):
    actor_id: Optional[uuid.UUID] = None


class ResumedEventDTO(BaseModel):
    id: uuid.UUID
    status: ChannelInboxStatusEnum
    quarantine_code: Optional[str] = None
    quarantine_reason: Optional[str] = None
    order_id: Optional[uuid.UUID] = None
    retention_until: Optional[datetime] = None


@router.post("/ingress/{provider_code}", response_model=IngressResponseDTO)
async def receive_channel_events(provider_code: str, request: Request, background: BackgroundTasks):
    # The signature is over the bytes as they arrived, so the body is read raw
    # and never re-serialized before the adapter sees it.
    body = await request.body()
    outcomes = await run_in_threadpool(ingress.receive, provider_code, dict(request.headers), body)
    received = {o.connection_id for o in outcomes if o.outcome == ingress.IngressOutcomeEnum.RECEIVED and o.connection_id}
    if received:
        background.add_task(inbox.process_connections, received)
    return {"events": [
        {"provider_event_id": outcome.provider_event_id, "outcome": outcome.outcome}
        for outcome in outcomes
    ]}


@router.post("/inbox/{event_id}/resume", response_model=ResumedEventDTO)
def resume_channel_event(
    event_id: uuid.UUID, data: ResumeDTO,
    context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session),
):
    return inbox.resume(session, context, event_id, resolve_actor(context, data.actor_id))


class OutboundNoticeDTO(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    external_order_id: Optional[str] = None
    message_type: str
    status: ChannelOutboundStatusEnum
    attempt_count: int
    last_error_code: Optional[str] = None
    next_retry_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    created_at: datetime


class DeadlineSummaryDTO(BaseModel):
    measured_at: datetime
    orders_awaiting_terminal: int
    oldest_awaiting_terminal_created_at: Optional[datetime] = None
    overdue_events: int
    overdue_contacts: int
    oldest_overdue_until: Optional[datetime] = None
    cleanup_exists: bool
    last_cleanup_at: Optional[datetime] = None


@router.get("/deadlines", response_model=DeadlineSummaryDTO)
def channel_data_deadlines(
    context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session),
):
    return retention.deadline_summary(session, context.tenant_id, context.store_id)


class ResendDTO(BaseModel):
    actor_id: Optional[uuid.UUID] = None


@router.get("/outbound", response_model=list[OutboundNoticeDTO])
def list_channel_notices(
    limit: int = 100,
    context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session),
):
    return outbound.list_messages(session, context, min(max(limit, 1), 500))


@router.post("/outbound/{message_id}/resend", response_model=OutboundNoticeDTO)
def resend_channel_notice(
    message_id: uuid.UUID, data: ResendDTO,
    context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session),
):
    row = outbound.resend(session, context, message_id, resolve_actor(context, data.actor_id))
    return outbound.list_messages(session, context, 1, message_id=row.id)[0]
