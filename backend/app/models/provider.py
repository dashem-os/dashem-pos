import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from decimal import Decimal

from sqlalchemy import Column, JSON, Numeric, Text
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.db_types import EnumString


class ProviderConfigurationStatusEnum(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BridgeTerminalStatusEnum(str, Enum):
    UNPAIRED = "UNPAIRED"
    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"


class PaymentDeviceExecutionModeEnum(str, Enum):
    """How Dashem sends a card payment to a physical payment device.

    SMARTPOS is intentionally only an enrollment mode here.  It must not be
    treated as an executable integration until an accredited adapter is
    installed and the device is actually paired.
    """

    TEF_BRIDGE = "TEF_BRIDGE"
    SMARTPOS = "SMARTPOS"


class PaymentDeviceBindingStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REVOKED = "REVOKED"


class ProviderTransactionStatusEnum(str, Enum):
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    UNKNOWN = "UNKNOWN"
    REFUNDED = "REFUNDED"


class PaymentExecutionStageEnum(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    RESULT_RECORDED = "RESULT_RECORDED"


class PaymentProviderConfiguration(SQLModel, table=True):
    __tablename__ = "payment_provider_configurations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "store_id", "provider_code", name="uq_store_provider_configuration"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    provider_code: str = Field(max_length=80, index=True)
    adapter_version: str = Field(default="1.0.0", max_length=40)
    status: ProviderConfigurationStatusEnum = Field(
        default=ProviderConfigurationStatusEnum.NOT_CONFIGURED,
        sa_column=Column(EnumString(ProviderConfigurationStatusEnum), nullable=False, index=True),
    )
    credentials_ref: Optional[str] = Field(default=None, max_length=255)
    timeout_seconds: int = Field(default=60, ge=5, le=600)
    configured_by: uuid.UUID = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TefBridgeTerminal(SQLModel, table=True):
    __tablename__ = "tef_bridge_terminals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "store_id", "register_id", name="uq_tef_bridge_register"),
        UniqueConstraint("tenant_id", "terminal_code", name="uq_tenant_bridge_terminal_code"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    register_id: uuid.UUID = Field(foreign_key="registers.id", index=True)
    provider_configuration_id: uuid.UUID = Field(foreign_key="payment_provider_configurations.id", index=True)
    terminal_code: str = Field(max_length=80, index=True)
    pairing_secret_hash: str = Field(max_length=64)
    bridge_version: Optional[str] = Field(default=None, max_length=40)
    protocol_version: str = Field(default="1.0", max_length=20)
    status: BridgeTerminalStatusEnum = Field(
        default=BridgeTerminalStatusEnum.UNPAIRED,
        sa_column=Column(EnumString(BridgeTerminalStatusEnum), nullable=False, index=True),
    )
    last_heartbeat_at: Optional[datetime] = Field(default=None, index=True)
    last_operation_at: Optional[datetime] = Field(default=None, index=True)
    last_error_code: Optional[str] = Field(default=None, max_length=80)
    last_error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    paired_by: uuid.UUID = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PaymentDeviceBinding(SQLModel, table=True):
    """The authoritative, unit-scoped route from a POS to card execution.

    A browser never picks a provider configuration or a bridge terminal at
    payment time.  It can only use this persisted binding, whose complete
    tenant/store/register/device chain is revalidated on the server.
    """

    __tablename__ = "payment_device_bindings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "operational_device_id", name="uq_payment_binding_operational_device"),
        UniqueConstraint(
            "tenant_id", "store_id", "provider_configuration_id", "external_device_reference",
            name="uq_payment_binding_provider_device_ref",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    register_id: uuid.UUID = Field(foreign_key="registers.id", index=True)
    operational_device_id: uuid.UUID = Field(foreign_key="operational_devices.id", index=True)
    provider_configuration_id: uuid.UUID = Field(foreign_key="payment_provider_configurations.id", index=True)
    tef_bridge_terminal_id: Optional[uuid.UUID] = Field(default=None, foreign_key="tef_bridge_terminals.id", index=True)
    execution_mode: PaymentDeviceExecutionModeEnum = Field(
        sa_column=Column(EnumString(PaymentDeviceExecutionModeEnum), nullable=False, index=True),
    )
    external_device_reference: Optional[str] = Field(default=None, max_length=160, index=True)
    status: PaymentDeviceBindingStatusEnum = Field(
        default=PaymentDeviceBindingStatusEnum.ACTIVE,
        sa_column=Column(EnumString(PaymentDeviceBindingStatusEnum), nullable=False, index=True),
    )
    configured_by: uuid.UUID = Field(index=True)
    paused_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProviderTransaction(SQLModel, table=True):
    __tablename__ = "provider_transactions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_provider_transaction_key"),
        UniqueConstraint("tenant_id", "provider_code", "external_transaction_id", name="uq_provider_external_transaction"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    payment_intent_id: uuid.UUID = Field(foreign_key="payment_intents.id", index=True)
    payment_device_binding_id: Optional[uuid.UUID] = Field(default=None, foreign_key="payment_device_bindings.id", index=True)
    provider_configuration_id: uuid.UUID = Field(foreign_key="payment_provider_configurations.id", index=True)
    bridge_terminal_id: Optional[uuid.UUID] = Field(default=None, foreign_key="tef_bridge_terminals.id", index=True)
    provider_code: str = Field(max_length=80, index=True)
    adapter_version: str = Field(max_length=40)
    status: ProviderTransactionStatusEnum = Field(
        default=ProviderTransactionStatusEnum.CREATED,
        sa_column=Column(EnumString(ProviderTransactionStatusEnum), nullable=False, index=True),
    )
    external_transaction_id: Optional[str] = Field(default=None, max_length=160, index=True)
    nsu: Optional[str] = Field(default=None, max_length=80, index=True)
    authorization_code: Optional[str] = Field(default=None, max_length=80)
    acquirer: Optional[str] = Field(default=None, max_length=120)
    card_brand: Optional[str] = Field(default=None, max_length=80)
    correlation_id: str = Field(max_length=160, index=True)
    idempotency_key: str = Field(max_length=160, index=True)
    request_hash: str = Field(max_length=64)
    sanitized_payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    failure_code: Optional[str] = Field(default=None, max_length=80)
    failure_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_by: uuid.UUID = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_queried_at: Optional[datetime] = Field(default=None, index=True)
    completed_at: Optional[datetime] = Field(default=None, index=True)


class ProviderTransactionEvent(SQLModel, table=True):
    __tablename__ = "provider_transaction_events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    provider_transaction_id: uuid.UUID = Field(foreign_key="provider_transactions.id", ondelete="CASCADE", index=True)
    event_type: str = Field(max_length=80, index=True)
    actor_id: uuid.UUID = Field(index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class PaymentExecutionEvent(SQLModel, table=True):
    """Append-only payment authority fact with its complete operational scope."""

    __tablename__ = "payment_execution_events"
    __table_args__ = (
        UniqueConstraint("provider_transaction_id", "sequence", name="uq_payment_execution_event_sequence"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    register_id: uuid.UUID = Field(foreign_key="registers.id", index=True)
    operational_device_id: uuid.UUID = Field(foreign_key="operational_devices.id", index=True)
    operational_session_id: Optional[uuid.UUID] = Field(default=None, foreign_key="operational_sessions.id", index=True)
    operational_actor_id: Optional[uuid.UUID] = Field(default=None, index=True)
    event_actor_id: uuid.UUID = Field(index=True)
    payment_intent_id: uuid.UUID = Field(foreign_key="payment_intents.id", index=True)
    payment_device_binding_id: uuid.UUID = Field(foreign_key="payment_device_bindings.id", index=True)
    provider_transaction_id: uuid.UUID = Field(foreign_key="provider_transactions.id", index=True)
    stage: PaymentExecutionStageEnum = Field(
        sa_column=Column(EnumString(PaymentExecutionStageEnum), nullable=False, index=True),
    )
    sequence: int = Field(index=True)
    amount: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    outcome: Optional[str] = Field(default=None, max_length=50, index=True)
    request_hash: str = Field(max_length=64, index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    occurred_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class OperationalProductivityProjection(SQLModel, table=True):
    """Rebuildable per-shift read model derived exclusively from immutable events."""

    __tablename__ = "operational_productivity_projections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "operational_session_id", name="uq_operational_productivity_session"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    register_id: uuid.UUID = Field(foreign_key="registers.id", index=True)
    operational_device_id: uuid.UUID = Field(foreign_key="operational_devices.id", index=True)
    operational_session_id: uuid.UUID = Field(foreign_key="operational_sessions.id", index=True)
    operator_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    requested_count: int = Field(default=0)
    approved_count: int = Field(default=0)
    executed_count: int = Field(default=0)
    confirmed_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    requested_amount: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    confirmed_amount: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    first_event_at: datetime = Field(index=True)
    last_event_at: datetime = Field(index=True)
    projection_version: int = Field(default=1)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
