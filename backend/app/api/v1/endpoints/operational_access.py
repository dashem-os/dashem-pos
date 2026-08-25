import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.identity import OperationalSessionStatusEnum, RoleEnum
from app.services import operational_access_service


router = APIRouter()


class OperationalSessionRead(BaseModel):
    access_token: str
    token_type: str
    expires_at: datetime
    user_id: uuid.UUID
    membership_id: uuid.UUID
    full_name: str
    role: RoleEnum
    store_id: uuid.UUID
    register_id: uuid.UUID | None = None


class TerminalTokenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    terminal_token: str = Field(min_length=40)


class TerminalLoginInput(TerminalTokenInput):
    employee_code: str = Field(min_length=3, max_length=20)
    pin: str = Field(min_length=4, max_length=8)


class OperationalSessionEndInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="Encerramento voluntário do turno", min_length=3, max_length=500)


class OperationalSessionHeartbeatRead(BaseModel):
    id: uuid.UUID
    status: OperationalSessionStatusEnum
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    register_id: uuid.UUID
    device_id: uuid.UUID
    last_seen_at: datetime
    expires_at: datetime


class TerminalContextRead(BaseModel):
    device_id: uuid.UUID
    device_name: str
    tenant_id: uuid.UUID
    tenant_name: str
    store_id: uuid.UUID
    store_name: str
    register_id: uuid.UUID
    register_name: str


class TerminalAuthorizationRead(TerminalContextRead):
    terminal_token: str
    expires_at: datetime


@router.post("/terminals/{device_id}/authorize", response_model=TerminalAuthorizationRead)
def authorize_terminal(
    device_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return operational_access_service.authorize_terminal(session, context, device_id)


@router.post("/terminal/status", response_model=TerminalContextRead)
def terminal_status(data: TerminalTokenInput, session: Session = Depends(get_session)):
    return operational_access_service.terminal_status(session, data.terminal_token)


@router.post("/terminal/login", response_model=OperationalSessionRead)
def terminal_login(data: TerminalLoginInput, session: Session = Depends(get_session)):
    return operational_access_service.activate_from_terminal(
        session,
        terminal_token=data.terminal_token,
        employee_code=data.employee_code,
        pin=data.pin,
    )


@router.post("/session/end", status_code=status.HTTP_204_NO_CONTENT)
def end_operational_session(
    data: OperationalSessionEndInput,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    operational_access_service.end_operational_session(session, context, reason=data.reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/session/heartbeat", response_model=OperationalSessionHeartbeatRead)
def heartbeat_operational_session(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return operational_access_service.heartbeat_operational_session(session, context)
