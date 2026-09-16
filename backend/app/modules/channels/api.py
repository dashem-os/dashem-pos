"""The routes the channels module owns.

`POST /channels/ingress/{provider_code}` carries no user session and passes
through no user permission: the caller is the channel, and it proves itself by
the signature its adapter checks. The response says what happened to each event
so the channel can stop resending what was kept; applying them to orders runs
right after the response (trigger (a) of the inbox).

`POST /channels/inbox/{event_id}/resume` is a person retaking a quarantined or
reviewed event. It is a `/channels` mutation, so the route map requires
`channel.manage`; it never moves a retention deadline.
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
from app.models.channel_hub import ChannelInboxStatusEnum
from app.modules.channels import inbox, ingress


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
