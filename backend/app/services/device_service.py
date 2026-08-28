import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.device import OperationalDevice, OperationalDeviceStatusEnum, OperationalDeviceTypeEnum
from app.models.identity import OperationalSession, OperationalSessionStatusEnum
from app.models.payment import Register
from app.models.production import ProductionPoint, ProductionPointTypeEnum
from app.services import reliability_service
from app.services.contract_limit_service import effective_limit
from app.services.operational_session_service import mark_expired


def _actor(context: TenantContext, actor_id: Optional[uuid.UUID]) -> uuid.UUID:
    return resolve_actor(context, actor_id)


def list_devices(session: Session, context: TenantContext) -> list[OperationalDevice]:
    return list(session.exec(scope_tenant_query(select(OperationalDevice), OperationalDevice, context).order_by(
        OperationalDevice.device_type, OperationalDevice.name,
    )).all())


def create_device(
    session: Session, context: TenantContext, *, store_id: uuid.UUID, code: str, name: str,
    device_type: OperationalDeviceTypeEnum, register_id: Optional[uuid.UUID],
    production_point_id: Optional[uuid.UUID], point_type: Optional[ProductionPointTypeEnum],
    configuration_ref: Optional[str],
    actor_id: Optional[uuid.UUID],
) -> OperationalDevice:
    if context.store_id and context.store_id != store_id:
        raise HTTPException(status_code=403, detail="Unidade fora do contexto ativo.")
    device_limit = effective_limit(session, context.tenant_id, "devices")
    active_devices = len(session.exec(select(OperationalDevice).where(
        OperationalDevice.tenant_id == context.tenant_id,
        OperationalDevice.status != OperationalDeviceStatusEnum.REVOKED,
    )).all())
    if device_limit is not None and active_devices >= device_limit:
        raise HTTPException(status_code=409, detail="Limite contratual de dispositivos atingido.")
    actor = _actor(context, actor_id)
    normalized_code = code.strip().upper()
    if session.exec(scope_tenant_query(select(OperationalDevice).where(
        OperationalDevice.store_id == store_id, OperationalDevice.code == normalized_code,
    ), OperationalDevice, context)).first():
        raise HTTPException(status_code=409, detail="Já existe um dispositivo com este código.")
    if device_type == OperationalDeviceTypeEnum.POS:
        register = session.get(Register, register_id) if register_id else Register(
            tenant_id=context.tenant_id, store_id=store_id, code=normalized_code, name=name.strip(),
        )
        if register_id is None:
            session.add(register)
            session.flush()
        if not register or register.tenant_id != context.tenant_id or register.store_id != store_id:
            raise HTTPException(status_code=400, detail="Terminal POS requer um caixa válido da unidade.")
        register_id = register.id
        production_point_id = None
    else:
        effective_point_type = ProductionPointTypeEnum.PRINTER if device_type == OperationalDeviceTypeEnum.PRINTER else point_type
        if production_point_id is None and device_type == OperationalDeviceTypeEnum.KDS and effective_point_type in (None, ProductionPointTypeEnum.PRINTER):
            raise HTTPException(status_code=400, detail="Terminal KDS requer um setor de produção válido.")
        point = session.get(ProductionPoint, production_point_id) if production_point_id else ProductionPoint(
            tenant_id=context.tenant_id, store_id=store_id, code=normalized_code, name=name.strip(),
            point_type=effective_point_type,
            printer_configuration_ref=configuration_ref.strip() if configuration_ref else None,
        )
        if production_point_id is None:
            session.add(point)
            session.flush()
        if not point or point.tenant_id != context.tenant_id or point.store_id != store_id:
            raise HTTPException(status_code=400, detail="KDS ou impressora requer um ponto de produção válido.")
        if device_type == OperationalDeviceTypeEnum.PRINTER and point.point_type != ProductionPointTypeEnum.PRINTER:
            raise HTTPException(status_code=400, detail="Impressora deve apontar para um ponto do tipo PRINTER.")
        if device_type == OperationalDeviceTypeEnum.KDS and point.point_type == ProductionPointTypeEnum.PRINTER:
            raise HTTPException(status_code=400, detail="KDS não pode apontar para um ponto de impressão.")
        production_point_id = point.id
        register_id = None
    device = OperationalDevice(
        tenant_id=context.tenant_id, store_id=store_id, code=normalized_code, name=name.strip(),
        device_type=device_type, register_id=register_id, production_point_id=production_point_id,
        configuration_ref=configuration_ref.strip() if configuration_ref else None,
    )
    session.add(device)
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=store_id, actor_id=actor,
        action="operational_device.created", target=f"DEVICE-{device.id}",
        audit_payload={"code": device.code, "name": device.name, "type": device.device_type.value},
        aggregate_type="operational_device", aggregate_id=str(device.id), event_type="operational_device.created",
        outbox_payload={"device_id": str(device.id), "store_id": str(store_id)},
    )
    session.commit(); session.refresh(device)
    return device


def update_device(
    session: Session, context: TenantContext, device_id: uuid.UUID, *, name: Optional[str],
    status: Optional[OperationalDeviceStatusEnum], configuration_ref: Optional[str],
    actor_id: Optional[uuid.UUID], reason: str,
) -> OperationalDevice:
    device = session.exec(scope_tenant_query(select(OperationalDevice).where(
        OperationalDevice.id == device_id,
    ), OperationalDevice, context).with_for_update()).first()
    if not device:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado.")
    actor = _actor(context, actor_id)
    if device.status == OperationalDeviceStatusEnum.REVOKED and status != OperationalDeviceStatusEnum.REVOKED:
        raise HTTPException(status_code=409, detail="Dispositivo revogado não pode ser reativado; faça novo pareamento.")
    if name is not None:
        device.name = name.strip()
    if status is not None:
        if status != device.status:
            device.authorization_version += 1
            device.authorized_at = None
            device.authorized_by = None
            device.authorization_expires_at = None
            active_sessions = session.exec(select(OperationalSession).where(
                OperationalSession.device_id == device.id,
                OperationalSession.status == OperationalSessionStatusEnum.ACTIVE,
            ).with_for_update()).all()
            for active_session in active_sessions:
                if mark_expired(session, active_session, now=datetime.utcnow()):
                    continue
                active_session.status = OperationalSessionStatusEnum.REVOKED
                active_session.ended_at = datetime.utcnow()
                active_session.end_reason = f"Dispositivo alterado para {status.value}: {reason}"[:500]
                session.add(active_session)
        device.status = status
    if configuration_ref is not None:
        device.configuration_ref = configuration_ref.strip() or None
    device.updated_at = datetime.utcnow()
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=device.store_id, actor_id=actor,
        action="operational_device.updated", target=f"DEVICE-{device.id}",
        audit_payload={"status": device.status.value, "reason": reason},
        aggregate_type="operational_device", aggregate_id=str(device.id), event_type="operational_device.updated",
        outbox_payload={"device_id": str(device.id), "status": device.status.value},
    )
    session.add(device); session.commit(); session.refresh(device)
    return device


def heartbeat(session: Session, context: TenantContext, device_id: uuid.UUID) -> OperationalDevice:
    device = session.exec(scope_tenant_query(select(OperationalDevice).where(
        OperationalDevice.id == device_id,
    ), OperationalDevice, context)).first()
    if not device:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado.")
    if device.status != OperationalDeviceStatusEnum.ACTIVE:
        raise HTTPException(status_code=403, detail="Dispositivo não está autorizado a operar.")
    device.last_seen_at = datetime.utcnow(); device.updated_at = device.last_seen_at
    session.add(device); session.commit(); session.refresh(device)
    return device
