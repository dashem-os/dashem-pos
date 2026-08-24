import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.identity import RoleEnum
from app.services import operational_access_service


router = APIRouter()


class OperationalActivation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_code: str = Field(min_length=3, max_length=20)
    pin: str = Field(min_length=4, max_length=8)
    store_id: uuid.UUID
    register_id: uuid.UUID | None = None


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


@router.post("/activate", response_model=OperationalSessionRead)
def activate_operational_access(
    data: OperationalActivation,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return operational_access_service.activate(
        session,
        context,
        employee_code=data.employee_code,
        pin=data.pin,
        store_id=data.store_id,
        register_id=data.register_id,
    )
