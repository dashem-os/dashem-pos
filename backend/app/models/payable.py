"""O que a loja deve, e para quem.

O inventário da UX-10 não achou nada de contas a pagar: nenhum modelo, nenhuma
tabela, nenhuma rota. Achou o espelho inteiro — `receivables`, com razão de
lançamentos, chave de idempotência, `version` e estorno. Este módulo segue a
mesma gramática de propósito: não há razão para o mesmo produto ter duas formas
de escrever dinheiro.

**Nada aqui nasce sozinho.** Registrar recebimento de mercadoria não cria conta
a pagar — a mercadoria pode ter sido paga à vista, ser consignada, bonificação
ou troca de avaria. E dar baixa numa conta não movimenta estoque. O elo entre os
dois é opcional e humano: quem lança pode apontar o fornecedor, e é só isso.

**"Vencida" não é situação gravada.** Ela é derivada de `due_on` contra hoje, e
gravá-la exigiria alguém passar virando linhas à meia-noite — que é exatamente o
processo que não existe. A situação guardada diz o que aconteceu com o dinheiro;
o calendário responde o resto.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import CheckConstraint, Column, Index, Numeric, Text, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from app.core.db_types import EnumString


class PayableStatusEnum(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    #: Lançada por engano. Diferente de reverter pagamento, e não se confunde
    #: com ela: aqui a dívida nunca existiu.
    ARCHIVED = "ARCHIVED"


class PayableEntryTypeEnum(str, Enum):
    #: O lançamento que abre a conta.
    ISSUE = "ISSUE"
    #: Uma baixa, total ou parcial.
    PAYMENT = "PAYMENT"
    #: Juros, multa ou abatimento **digitados por uma pessoa**, com motivo. O
    #: sistema não calcula nenhum dos três: regra de cálculo é decisão do dono,
    #: e escolher uma para desbloquear a sprint é como o número fica errado.
    ADJUSTMENT = "ADJUSTMENT"
    #: Desfaz uma baixa registrada por engano. Não apaga nada.
    REVERSAL = "REVERSAL"


class Payable(SQLModel, table=True):
    __tablename__ = "payables"
    __table_args__ = (
        UniqueConstraint("tenant_id", "issue_idempotency_key", name="uq_tenant_payable_issue_key"),
        CheckConstraint("principal_amount > 0", name="ck_payable_principal_positive"),
        CheckConstraint("paid_amount >= 0", name="ck_payable_paid_nonnegative"),
        CheckConstraint("balance >= 0", name="ck_payable_balance_nonnegative"),
        CheckConstraint("version > 0", name="ck_payable_version_positive"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    #: Opcional: a conta de luz é da empresa, não de uma unidade.
    store_id: Optional[uuid.UUID] = Field(default=None, foreign_key="stores.id", index=True)

    #: O favorecido tem duas formas de primeira classe. Vinculado ao cadastro da
    #: UX-09 quando é fornecedor; e o nome sempre fica gravado aqui, porque a
    #: conta precisa continuar legível se o fornecedor for arquivado depois.
    supplier_id: Optional[uuid.UUID] = Field(default=None, foreign_key="suppliers.id", index=True)
    payee_name: str = Field(max_length=160, index=True)

    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    status: PayableStatusEnum = Field(
        default=PayableStatusEnum.OPEN,
        sa_column=Column(EnumString(PayableStatusEnum), nullable=False, index=True),
    )
    principal_amount: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    paid_amount: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    balance: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))

    #: Data, não instante: vencimento é dia de calendário, e guardar hora faria
    #: "vence hoje" depender do fuso de quem pergunta.
    due_on: date = Field(index=True)
    issued_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    #: Concorrência otimista: duas pessoas dando baixa ao mesmo tempo não
    #: gravam duas. Quem perde a corrida é recusado com o saldo atual à vista.
    version: int = Field(default=1)
    issue_idempotency_key: str = Field(max_length=160, index=True)
    archived_at: Optional[datetime] = Field(default=None, index=True)
    archived_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_by: uuid.UUID = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PayableLedgerEntry(SQLModel, table=True):
    """A razão da conta: o que aconteceu, quando, de quem partiu e por quê.

    Nada é apagado nem sobrescrito. Reverter uma baixa é **outro** lançamento
    que aponta para o primeiro, e a tela mostra os dois — quem confere precisa
    ver que houve um engano e que ele foi desfeito, não uma conta que sempre
    esteve certa.
    """

    __tablename__ = "payable_ledger_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_payable_ledger_key"),
        CheckConstraint("amount <> 0", name="ck_payable_ledger_amount_nonzero"),
        # Uma baixa só se desfaz uma vez. Sem isto, dois cliques em "Reverter"
        # devolveriam o saldo duas vezes e a conta passaria a dever mais do que
        # devia — em silêncio, porque cada lançamento é válido sozinho.
        Index(
            "uq_payable_reversal_once", "reverses_entry_id",
            unique=True, postgresql_where=text("reverses_entry_id IS NOT NULL"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    payable_id: uuid.UUID = Field(foreign_key="payables.id", ondelete="RESTRICT", index=True)
    entry_type: PayableEntryTypeEnum = Field(
        sa_column=Column(EnumString(PayableEntryTypeEnum), nullable=False, index=True)
    )
    #: Positivo aumenta o que se deve, negativo abate. Uma baixa é negativa.
    amount: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    #: "Dinheiro", "Pix", "Transferência" — a palavra de quem paga, não uma
    #: lista fechada: a operação real usa formas que nenhum enum previu.
    method: Optional[str] = Field(default=None, max_length=60)
    reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    #: A baixa que este lançamento desfaz. Só a reversão preenche.
    reverses_entry_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="payable_ledger_entries.id", index=True,
    )
    occurred_on: date = Field(index=True)
    idempotency_key: str = Field(max_length=160, index=True)
    created_by: uuid.UUID = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
