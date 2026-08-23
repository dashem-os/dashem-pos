import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.provider import (
    BridgeTerminalStatusEnum, ProviderConfigurationStatusEnum,
    ProviderTransactionStatusEnum,
)
from app.services import provider_service


router = APIRouter()


class ProviderConfigurationCreateDTO(BaseModel):
    store_id: uuid.UUID
    provider_code: str = Field(min_length=2, max_length=80)
    credentials_ref: Optional[str] = Field(default=None, max_length=255)
    timeout_seconds: int = Field(default=60, ge=5, le=600)
    actor_id: Optional[uuid.UUID] = None


class ProviderConfigurationDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    provider_code: str
    adapter_version: str
    status: ProviderConfigurationStatusEnum
    timeout_seconds: int
    created_at: datetime
    updated_at: datetime


class TerminalPairDTO(BaseModel):
    store_id: uuid.UUID
    register_id: uuid.UUID
    provider_configuration_id: uuid.UUID
    terminal_code: str = Field(min_length=2, max_length=80)
    actor_id: Optional[uuid.UUID] = None


class TerminalDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    register_id: uuid.UUID
    provider_configuration_id: uuid.UUID
    terminal_code: str
    bridge_version: Optional[str]
    protocol_version: str
    status: BridgeTerminalStatusEnum
    last_heartbeat_at: Optional[datetime]
    last_operation_at: Optional[datetime]
    last_error_code: Optional[str]
    last_error_message: Optional[str]


class TerminalPairResponseDTO(BaseModel):
    terminal: TerminalDTO
    pairing_code: str


class BridgeHeartbeatDTO(BaseModel):
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    pairing_code: str = Field(min_length=20)
    bridge_version: str = Field(min_length=1, max_length=40)
    protocol_version: str = Field(default="1.0", max_length=20)
    last_error_code: Optional[str] = Field(default=None, max_length=80)
    last_error_message: Optional[str] = Field(default=None, max_length=300)


class ProviderTransactionExecuteDTO(BaseModel):
    payment_intent_id: uuid.UUID
    provider_configuration_id: uuid.UUID
    bridge_terminal_id: uuid.UUID
    actor_id: Optional[uuid.UUID] = None
    test_outcome: Optional[ProviderTransactionStatusEnum] = None


class ProviderTransactionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    payment_intent_id: uuid.UUID
    provider_configuration_id: uuid.UUID
    bridge_terminal_id: Optional[uuid.UUID]
    provider_code: str
    adapter_version: str
    status: ProviderTransactionStatusEnum
    external_transaction_id: Optional[str]
    nsu: Optional[str]
    authorization_code: Optional[str]
    acquirer: Optional[str]
    card_brand: Optional[str]
    correlation_id: str
    sanitized_payload: dict
    failure_code: Optional[str]
    failure_reason: Optional[str]
    created_at: datetime
    updated_at: datetime
    last_queried_at: Optional[datetime]
    completed_at: Optional[datetime]


class ProviderExecutionDTO(BaseModel):
    transaction: ProviderTransactionDTO
    negotiation: dict


class ReconcileDTO(BaseModel):
    actor_id: Optional[uuid.UUID] = None
    test_outcome: Optional[ProviderTransactionStatusEnum] = None


class BridgeResultDTO(BaseModel):
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    pairing_code: str = Field(min_length=20)
    status: ProviderTransactionStatusEnum
    external_transaction_id: Optional[str] = Field(default=None, max_length=160)
    nsu: Optional[str] = Field(default=None, max_length=80)
    authorization_code: Optional[str] = Field(default=None, max_length=80)
    acquirer: Optional[str] = Field(default=None, max_length=120)
    card_brand: Optional[str] = Field(default=None, max_length=80)
    failure_code: Optional[str] = Field(default=None, max_length=80)
    failure_reason: Optional[str] = Field(default=None, max_length=300)


@router.post("/configurations", response_model=ProviderConfigurationDTO)
def configure_provider_endpoint(data: ProviderConfigurationCreateDTO, idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160), context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return provider_service.configure_provider(
        session, context, store_id=data.store_id, provider_code=data.provider_code,
        credentials_ref=data.credentials_ref, timeout_seconds=data.timeout_seconds,
        actor_id=data.actor_id, idempotency_key=idempotency_key,
    )


@router.get("/configurations", response_model=list[ProviderConfigurationDTO])
def list_provider_configurations_endpoint(context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return provider_service.list_configurations(session, context)


@router.post("/bridge/terminals", response_model=TerminalPairResponseDTO)
def pair_bridge_terminal_endpoint(data: TerminalPairDTO, idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160), context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    terminal, pairing_code = provider_service.pair_terminal(
        session, context, store_id=data.store_id, register_id=data.register_id,
        provider_configuration_id=data.provider_configuration_id,
        terminal_code=data.terminal_code, actor_id=data.actor_id, idempotency_key=idempotency_key,
    )
    return {"terminal": terminal, "pairing_code": pairing_code}


@router.get("/bridge/terminals", response_model=list[TerminalDTO])
def list_bridge_terminals_endpoint(register_id: Optional[uuid.UUID] = None, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return provider_service.list_terminals(session, context, register_id)


@router.post("/bridge/terminals/{terminal_id}/heartbeat", response_model=TerminalDTO)
def bridge_heartbeat_endpoint(terminal_id: uuid.UUID, data: BridgeHeartbeatDTO, session: Session = Depends(get_session)):
    return provider_service.heartbeat_terminal(
        session, terminal_id, pairing_secret=data.pairing_code,
        tenant_id=data.tenant_id, store_id=data.store_id,
        bridge_version=data.bridge_version, protocol_version=data.protocol_version,
        last_error_code=data.last_error_code, last_error_message=data.last_error_message,
    )


@router.post("/transactions", response_model=ProviderExecutionDTO)
def execute_provider_transaction_endpoint(
    data: ProviderTransactionExecuteDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    correlation_id: Optional[str] = Header(default=None, alias="X-Correlation-ID", max_length=160),
    context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session),
):
    return provider_service.execute_transaction(
        session, context, payment_intent_id=data.payment_intent_id,
        provider_configuration_id=data.provider_configuration_id,
        bridge_terminal_id=data.bridge_terminal_id, actor_id=data.actor_id,
        idempotency_key=idempotency_key, correlation_id=correlation_id,
        test_outcome=data.test_outcome.value if data.test_outcome else None,
    )


@router.post("/transactions/{transaction_id}/reconcile", response_model=ProviderExecutionDTO)
def reconcile_provider_transaction_endpoint(transaction_id: uuid.UUID, data: ReconcileDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return provider_service.reconcile_transaction(
        session, context, transaction_id, actor_id=data.actor_id,
        test_outcome=data.test_outcome.value if data.test_outcome else None,
    )


@router.post("/bridge/terminals/{terminal_id}/transactions/{transaction_id}/result", response_model=ProviderExecutionDTO)
def bridge_result_endpoint(terminal_id: uuid.UUID, transaction_id: uuid.UUID, data: BridgeResultDTO, session: Session = Depends(get_session)):
    return provider_service.report_bridge_result(
        session, terminal_id, transaction_id, pairing_secret=data.pairing_code,
        tenant_id=data.tenant_id, store_id=data.store_id, status_value=data.status,
        external_transaction_id=data.external_transaction_id, nsu=data.nsu,
        authorization_code=data.authorization_code, acquirer=data.acquirer,
        card_brand=data.card_brand, failure_code=data.failure_code,
        failure_reason=data.failure_reason,
    )
