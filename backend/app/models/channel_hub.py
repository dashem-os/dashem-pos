import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from decimal import Decimal

from sqlalchemy import CheckConstraint, Column, Index, Integer, JSON, Numeric, Text, text
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.db_types import EnumString


class MerchantConnectionStatusEnum(str, Enum):
    NOT_CONNECTED = "NOT_CONNECTED"
    VALIDATING = "VALIDATING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    SUSPENDED = "SUSPENDED"


class ChannelInboxStatusEnum(str, Enum):
    """Where an event is in the resumable inbox (S10.1, §3.4).

    `RECEIVED` is waiting to be processed, never a processed order. `DISCARDED`
    and `EXPIRED` are definitive: neither is retaken.
    """

    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    APPLIED = "APPLIED"
    SUPERSEDED = "SUPERSEDED"
    QUARANTINED = "QUARANTINED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    DISCARDED = "DISCARDED"
    EXPIRED = "EXPIRED"


class ExternalOrderTerminalStateEnum(str, Enum):
    CONCLUDED = "CONCLUDED"
    CANCELED = "CANCELED"


class ChannelOrderLineStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELED = "CANCELED"


class ChannelRedactionMethodEnum(str, Enum):
    ERASED = "ERASED"
    REDACTED = "REDACTED"
    PSEUDONYMIZED = "PSEUDONYMIZED"


LEGAL_HOLD_COMPLETE = (
    "(legal_hold_until IS NULL AND legal_hold_reason IS NULL AND legal_hold_reference IS NULL"
    " AND legal_hold_by IS NULL AND legal_hold_review_at IS NULL)"
    " OR (legal_hold_until IS NOT NULL AND legal_hold_reason IS NOT NULL"
    " AND legal_hold_reference IS NOT NULL AND legal_hold_by IS NOT NULL"
    " AND legal_hold_review_at IS NOT NULL)"
)


class ChannelRetentionBasisEnum(str, Enum):
    """De onde veio o prazo de um dado de canal (S10.1, §3.7.4)."""

    RECEPCAO = "RECEPCAO"
    ESTADO_TERMINAL = "ESTADO_TERMINAL"
    CLASSIFICACAO_DEFINITIVA = "CLASSIFICACAO_DEFINITIVA"


class ChannelOutboundStatusEnum(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    RETRY = "RETRY"
    DEAD_LETTER = "DEAD_LETTER"


class MerchantConnection(SQLModel, table=True):
    __tablename__ = "merchant_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider_code", "merchant_external_id", name="uq_provider_merchant_connection"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_merchant_connection_key"),
        # Um merchant conectado pertence a um único tenant. O ingresso resolve a
        # conexão pelo provedor e pelo merchant, sem tenant no corpo (H9): dois
        # tenants conectados ao mesmo merchant tornariam a entrega ambígua.
        Index(
            "uq_connected_provider_merchant", "provider_code", "merchant_external_id", unique=True,
            postgresql_where=text("status = 'CONNECTED'"),
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    channel_id: uuid.UUID = Field(foreign_key="sales_channels.id", index=True)
    provider_code: str = Field(max_length=80, index=True)
    adapter_version: str = Field(default="1.0.0", max_length=40)
    merchant_external_id: str = Field(max_length=160, index=True)
    status: MerchantConnectionStatusEnum = Field(default=MerchantConnectionStatusEnum.NOT_CONNECTED, sa_column=Column(EnumString(MerchantConnectionStatusEnum), nullable=False, index=True))
    credentials_ref: Optional[str] = Field(default=None, max_length=255)
    # Legado do S10: o canal assina com a credencial do aplicativo, não por conexão.
    webhook_secret_hash: Optional[str] = Field(default=None, max_length=64)
    service_actor_id: uuid.UUID = Field(index=True)
    idempotency_key: str = Field(max_length=160, index=True)
    request_hash: str = Field(max_length=64)
    configured_by: uuid.UUID = Field(index=True)
    last_validated_at: Optional[datetime] = Field(default=None, index=True)
    last_event_at: Optional[datetime] = Field(default=None, index=True)
    last_error_code: Optional[str] = Field(default=None, max_length=80)
    last_error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChannelInboxEvent(SQLModel, table=True):
    __tablename__ = "channel_inbox_events"
    __table_args__ = (
        UniqueConstraint("merchant_connection_id", "provider_event_id", name="uq_connection_provider_event"),
        # Legal hold vale só completo: motivo, referência, responsável e revisão (H16).
        CheckConstraint(LEGAL_HOLD_COMPLETE, name="ck_channel_inbox_legal_hold_complete"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    merchant_connection_id: uuid.UUID = Field(foreign_key="merchant_connections.id", index=True)
    provider_event_id: str = Field(max_length=160, index=True)
    external_order_id: str = Field(max_length=160, index=True)
    event_type: str = Field(max_length=80, index=True)
    payload_hash: str = Field(max_length=64)
    # Nulo só depois da purga, que ainda não existe (§3.7.5).
    raw_payload: Optional[dict] = Field(default_factory=dict, sa_column=Column(JSON, nullable=True))
    status: ChannelInboxStatusEnum = Field(default=ChannelInboxStatusEnum.RECEIVED, sa_column=Column(EnumString(ChannelInboxStatusEnum), nullable=False, index=True))
    order_id: Optional[uuid.UUID] = Field(default=None, foreign_key="orders.id", index=True)
    quarantine_code: Optional[str] = Field(default=None, max_length=80)
    quarantine_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    received_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    acknowledged_at: Optional[datetime] = Field(default=None, index=True)
    processed_at: Optional[datetime] = Field(default=None, index=True)
    # Caixa retomável (S10.1, passo 3).
    parser_version: Optional[str] = Field(default=None, max_length=40)
    order_key: Optional[str] = Field(default=None, max_length=40)
    attempts: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default="0"))
    lease_expires_at: Optional[datetime] = Field(default=None)
    last_error_code: Optional[str] = Field(default=None, max_length=80)
    # Uma vez segurado — quarentena ou revisão —, o prazo do payload segue contado
    # da recepção, mesmo que a causa seja corrigida e o evento aplicado depois (D6).
    first_quarantined_at: Optional[datetime] = Field(default=None)
    # D6: todo evento nasce com prazo. Política técnica inicial, não jurídica (§3.7.1).
    retention_basis: ChannelRetentionBasisEnum = Field(
        default=ChannelRetentionBasisEnum.RECEPCAO,
        sa_column=Column(EnumString(ChannelRetentionBasisEnum), nullable=False),
    )
    retention_until: Optional[datetime] = Field(default=None, index=True)
    legal_hold_until: Optional[datetime] = Field(default=None, index=True)
    legal_hold_reason: Optional[str] = Field(default=None, max_length=300)
    legal_hold_reference: Optional[str] = Field(default=None, max_length=160)
    legal_hold_by: Optional[uuid.UUID] = Field(default=None)
    legal_hold_review_at: Optional[datetime] = Field(default=None)


class ExternalOrderMapping(SQLModel, table=True):
    __tablename__ = "external_order_mappings"
    __table_args__ = (
        UniqueConstraint("merchant_connection_id", "external_order_id", name="uq_connection_external_order"),
        UniqueConstraint("tenant_id", "order_id", name="uq_tenant_external_order_mapping"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    merchant_connection_id: uuid.UUID = Field(foreign_key="merchant_connections.id", index=True)
    external_order_id: str = Field(max_length=160, index=True)
    order_id: uuid.UUID = Field(foreign_key="orders.id", index=True)
    payment_origin: Optional[str] = Field(default=None, max_length=80, index=True)
    # Evidência normalizada (S10.1, §3.5 e §3.7.3): nada aqui nomeia a pessoa.
    last_order_key: Optional[str] = Field(default=None, max_length=40)
    delivery_fee: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 4), nullable=True))
    channel_discount: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 4), nullable=True))
    channel_subsidy: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 4), nullable=True))
    declared_total: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 4), nullable=True))
    # A âncora dos prazos (D3): quando o pedido ficou terminal.
    terminal_state: Optional[ExternalOrderTerminalStateEnum] = Field(
        default=None, sa_column=Column(EnumString(ExternalOrderTerminalStateEnum), nullable=True),
    )
    terminal_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class ChannelOrderLine(SQLModel, table=True):
    """Uma linha do pedido como o canal a declarou, ligada ao item que ela abriu.

    A identidade é a linha externa, nunca o evento que a trouxe (H3): atualizar
    o pedido é comparar linhas externas, e repetir um evento não duplica nada.
    """

    __tablename__ = "external_order_lines"
    __table_args__ = (
        UniqueConstraint("external_order_mapping_id", "external_line_id", name="uq_external_order_line"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    external_order_mapping_id: uuid.UUID = Field(foreign_key="external_order_mappings.id", index=True)
    external_line_id: str = Field(max_length=160)
    external_item_code: str = Field(max_length=160)
    order_item_id: Optional[uuid.UUID] = Field(default=None, foreign_key="order_items.id", index=True)
    quantity: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    unit_amount: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 4), nullable=True))
    discount_amount: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 4), nullable=True))
    modifier_codes: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    status: ChannelOrderLineStatusEnum = Field(
        default=ChannelOrderLineStatusEnum.ACTIVE,
        sa_column=Column(EnumString(ChannelOrderLineStatusEnum), nullable=False),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChannelOrderContact(SQLModel, table=True):
    """A pessoa por trás do pedido de canal — a camada de dados operacionais pessoais.

    Existe só quando um evento é aplicado a um pedido (§3.7.4). É o único lugar
    onde nome, telefone, endereço e instruções de entrega moram (H13); nenhum
    deles vai para o pedido, para log ou para trilha imutável (H17). Nenhuma rota
    lê estes campos enquanto a permissão de leitura de contato da D7 não tiver
    concessão definida e testada.
    """

    __tablename__ = "channel_order_contacts"
    __table_args__ = (
        UniqueConstraint("external_order_mapping_id", name="uq_channel_order_contact_mapping"),
        CheckConstraint(LEGAL_HOLD_COMPLETE, name="ck_channel_contact_legal_hold_complete"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    external_order_mapping_id: uuid.UUID = Field(foreign_key="external_order_mappings.id", index=True)
    display_name: Optional[str] = Field(default=None, max_length=160)
    phone: Optional[str] = Field(default=None, max_length=40)
    delivery_address: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    delivery_instructions: Optional[str] = Field(default=None, max_length=500)
    pseudonym: str = Field(max_length=40)
    retention_basis: ChannelRetentionBasisEnum = Field(
        default=ChannelRetentionBasisEnum.ESTADO_TERMINAL,
        sa_column=Column(EnumString(ChannelRetentionBasisEnum), nullable=False),
    )
    retention_until: Optional[datetime] = Field(default=None, index=True)
    redacted_at: Optional[datetime] = Field(default=None)
    redaction_method: Optional[ChannelRedactionMethodEnum] = Field(
        default=None, sa_column=Column(EnumString(ChannelRedactionMethodEnum), nullable=True),
    )
    legal_hold_until: Optional[datetime] = Field(default=None, index=True)
    legal_hold_reason: Optional[str] = Field(default=None, max_length=300)
    legal_hold_reference: Optional[str] = Field(default=None, max_length=160)
    legal_hold_by: Optional[uuid.UUID] = Field(default=None)
    legal_hold_review_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChannelOutboundMessage(SQLModel, table=True):
    __tablename__ = "channel_outbound_messages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_channel_outbound_key"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    merchant_connection_id: uuid.UUID = Field(foreign_key="merchant_connections.id", index=True)
    order_id: uuid.UUID = Field(foreign_key="orders.id", index=True)
    message_type: str = Field(max_length=80, index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    status: ChannelOutboundStatusEnum = Field(default=ChannelOutboundStatusEnum.PENDING, sa_column=Column(EnumString(ChannelOutboundStatusEnum), nullable=False, index=True))
    attempt_count: int = Field(default=0, ge=0)
    idempotency_key: str = Field(max_length=160, index=True)
    request_hash: str = Field(max_length=64)
    last_error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    next_retry_at: Optional[datetime] = Field(default=None, index=True)
    created_by: uuid.UUID = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
