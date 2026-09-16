"""The routes the channels module owns.

`POST /channels/ingress/{provider_code}` carries no user session and passes
through no user permission: the caller is the channel, and it proves itself by
the signature its adapter checks. The response says what happened to each event
so the channel can stop resending what was kept.
"""

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.modules.channels import ingress


router = APIRouter()


class IngressEventOutcomeDTO(BaseModel):
    provider_event_id: str
    outcome: str


class IngressResponseDTO(BaseModel):
    events: list[IngressEventOutcomeDTO]


@router.post("/ingress/{provider_code}", response_model=IngressResponseDTO)
async def receive_channel_events(provider_code: str, request: Request):
    # The signature is over the bytes as they arrived, so the body is read raw
    # and never re-serialized before the adapter sees it.
    body = await request.body()
    outcomes = await run_in_threadpool(ingress.receive, provider_code, dict(request.headers), body)
    return {"events": [
        {"provider_event_id": outcome.provider_event_id, "outcome": outcome.outcome}
        for outcome in outcomes
    ]}
