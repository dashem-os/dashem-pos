import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.device import OperationalDeviceStatusEnum, OperationalDeviceTypeEnum
from app.models.production import ProductionPointTypeEnum
from app.services import device_service


router = APIRouter()


class DeviceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    code: str
    name: str
    device_type: OperationalDeviceTypeEnum
    status: OperationalDeviceStatusEnum
    register_id: Optional[uuid.UUID]
    production_point_id: Optional[uuid.UUID]
    configuration_ref: Optional[str]
    last_seen_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class DeviceCreateDTO(BaseModel):
    store_id: uuid.UUID
    code: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    device_type: OperationalDeviceTypeEnum
    register_id: Optional[uuid.UUID] = None
    production_point_id: Optional[uuid.UUID] = None
    point_type: Optional[ProductionPointTypeEnum] = None
    configuration_ref: Optional[str] = Field(default=None, max_length=255)
    actor_id: Optional[uuid.UUID] = None


class DeviceUpdateDTO(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    status: Optional[OperationalDeviceStatusEnum] = None
    configuration_ref: Optional[str] = Field(default=None, max_length=255)
    reason: str = Field(min_length=3, max_length=500)
    actor_id: Optional[uuid.UUID] = None


@router.get("", response_model=list[DeviceDTO])
def list_devices_endpoint(context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return device_service.list_devices(session, context)


@router.post("", response_model=DeviceDTO, status_code=201)
def create_device_endpoint(data: DeviceCreateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return device_service.create_device(session, context, store_id=data.store_id, code=data.code,
        name=data.name, device_type=data.device_type, register_id=data.register_id,
        production_point_id=data.production_point_id, point_type=data.point_type,
        configuration_ref=data.configuration_ref,
        actor_id=data.actor_id)


@router.patch("/{device_id}", response_model=DeviceDTO)
def update_device_endpoint(device_id: uuid.UUID, data: DeviceUpdateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return device_service.update_device(session, context, device_id, name=data.name, status=data.status,
        configuration_ref=data.configuration_ref, actor_id=data.actor_id, reason=data.reason)


@router.post("/{device_id}/heartbeat", response_model=DeviceDTO)
def heartbeat_endpoint(device_id: uuid.UUID, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return device_service.heartbeat(session, context, device_id)
