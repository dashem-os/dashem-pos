"""The tables this package owns: the command queue and the terminal occupancy.

They live beside the terminal they address, not inside `app/models/provider.py`:
code born after ADR-029 §1.2 is born in its module. The terminal itself
(`TefBridgeTerminal`) predates the rule and stays where it is; these tables
reference it by foreign key and never import it.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, Index, JSON, text
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.db_types import EnumString


class BridgeCommandTypeEnum(str, Enum):
    START = "START"
    CANCEL = "CANCEL"
    QUERY = "QUERY"
    REFUND = "REFUND"


class BridgeCommandClassEnum(str, Enum):
    """Transporte, não autorização.

    `EXECUTION` movimenta dinheiro no pinpad e é exclusiva por terminal.
    `CONTROL` fala *sobre* a operação em curso e nunca pode ficar bloqueada
    atrás dela — senão um cancelamento jamais chega a tempo. Classificar aqui
    não concede permissão nenhuma: cancelar tem autoridade própria.
    """

    EXECUTION = "EXECUTION"
    CONTROL = "CONTROL"


class BridgeCommandDeliveryStatusEnum(str, Enum):
    """Onde o comando está no fio — e só isso.

    Nenhum destes valores diz o que aconteceu com o dinheiro. `CLOSED` fecha o
    comando; a operação financeira tem eixo próprio em `FinancialResolutionEnum`.
    """

    PENDING = "PENDING"
    LEASED = "LEASED"
    ACKED = "ACKED"
    CLOSED = "CLOSED"


class FinancialResolutionEnum(str, Enum):
    """O que se sabe sobre o dinheiro.

    Não existe valor para "deu tempo": expiração de lease e tentativas esgotadas
    mantêm `INCERTA`, porque tempo não prova ausência de cobrança.
    """

    NAO_INICIADA = "NAO_INICIADA"
    INCERTA = "INCERTA"
    PROVADA_EXECUTADA = "PROVADA_EXECUTADA"
    PROVADA_NAO_EXECUTADA = "PROVADA_NAO_EXECUTADA"


class ExecutorNeutralizationEnum(str, Enum):
    """Por que um executor anterior não pode mais acionar o SDK.

    Consulta dizendo "não executou" descreve o passado; um processo suspenso que
    retoma é um fato do futuro. Sem uma destas registrada, a ocupação não sai.
    """

    PROVIDER_DEDUPLICATES = "PROVIDER_DEDUPLICATES"
    PROVIDER_INVALIDATED = "PROVIDER_INVALIDATED"
    ATTESTED_DECOMMISSIONED = "ATTESTED_DECOMMISSIONED"


class TefBridgeCommand(SQLModel, table=True):
    """Um pedido endereçado a um bridge pareado.

    O `id` é a identidade estável: reenviar repete a mesma identidade e nunca
    cria comando novo, porque é por ela que o bridge deduplica antes de acionar
    o pinpad. A idempotência do servidor não alcança o equipamento.
    """

    __tablename__ = "tef_bridge_commands"
    __table_args__ = (
        UniqueConstraint("bridge_terminal_id", "sequence", name="uq_bridge_command_terminal_sequence"),
        # O caminho quente da entrega: o que está pronto para este terminal, na ordem.
        Index(
            "ix_tef_bridge_commands_claimable",
            "bridge_terminal_id", "command_class", "sequence",
            postgresql_where=text("delivery_status IN ('PENDING', 'LEASED')"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    bridge_terminal_id: uuid.UUID = Field(foreign_key="tef_bridge_terminals.id", index=True)
    provider_transaction_id: uuid.UUID = Field(foreign_key="provider_transactions.id", index=True)
    command_type: BridgeCommandTypeEnum = Field(
        sa_column=Column(EnumString(BridgeCommandTypeEnum), nullable=False, index=True),
    )
    command_class: BridgeCommandClassEnum = Field(
        sa_column=Column(EnumString(BridgeCommandClassEnum), nullable=False, index=True),
    )
    sequence: int = Field()
    delivery_status: BridgeCommandDeliveryStatusEnum = Field(
        default=BridgeCommandDeliveryStatusEnum.PENDING,
        sa_column=Column(EnumString(BridgeCommandDeliveryStatusEnum), nullable=False, index=True),
    )
    installation_epoch: int = Field(default=0)
    # Quando o comando pode sair de novo: agora, para o que espera na fila; o fim
    # do lease, para o que já foi entregue. Um só relógio para as duas esperas.
    available_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    attempts: int = Field(default=0)
    delivered_at: Optional[datetime] = Field(default=None)
    acked_at: Optional[datetime] = Field(default=None)
    closed_at: Optional[datetime] = Field(default=None)
    closed_reason: Optional[str] = Field(default=None, max_length=80)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    correlation_id: str = Field(max_length=160)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TefTerminalOccupancy(SQLModel, table=True):
    """O terminal está tomado por uma operação financeira ainda não provada.

    O cadeado não é a chave primária: é o índice parcial `uq_terminal_occupied`
    sobre `released_at IS NULL`, criado na migração 097. Com o terminal como
    chave, preencher `released_at` deixaria a linha ocupando a chave e travaria
    o caixa para sempre.

    Liberar confere sempre a operação proprietária — transação **e** o que foi
    pedido a ela, porque o estorno anda sobre a cobrança que reverte e divide a
    transação com ela. Ver `occupancy.release_occupancy`.
    """

    __tablename__ = "tef_terminal_occupancy"
    __table_args__ = (
        # O cadeado. Uma ocupação viva por terminal, e o histórico fica: com o
        # terminal como chave primária, preencher `released_at` deixava a linha
        # ocupando a chave e travava o caixa para sempre.
        Index(
            "uq_terminal_occupied", "bridge_terminal_id", unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    bridge_terminal_id: uuid.UUID = Field(foreign_key="tef_bridge_terminals.id", index=True)
    provider_transaction_id: uuid.UUID = Field(foreign_key="provider_transactions.id", index=True)
    operation: BridgeCommandTypeEnum = Field(
        sa_column=Column(EnumString(BridgeCommandTypeEnum), nullable=False),
    )
    financial_resolution: FinancialResolutionEnum = Field(
        default=FinancialResolutionEnum.INCERTA,
        sa_column=Column(EnumString(FinancialResolutionEnum), nullable=False, index=True),
    )
    neutralization: Optional[ExecutorNeutralizationEnum] = Field(
        default=None, sa_column=Column(EnumString(ExecutorNeutralizationEnum), nullable=True),
    )
    acquired_epoch: int = Field(default=0)
    acquired_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    released_at: Optional[datetime] = Field(default=None)
    released_reason: Optional[str] = Field(default=None, max_length=120)
    released_by: Optional[uuid.UUID] = Field(default=None)
