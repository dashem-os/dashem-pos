"""Quem fornece a mercadoria.

O inventário da UX-09 não achou nada: nem modelo, nem tabela, nem rota. Duas
linhas de comentário no código citavam "fornecedor" como assunto de uma etapa
futura, e era só isso. Então este é domínio novo, e o que ele **não** faz
importa tanto quanto o que faz.

**Não há pedido de compra aqui.** O enunciado é explícito: não inventar pedido
de compra como entregue. O que existe é o cadastro de quem fornece, seus
contatos, e o vínculo do recebimento com ele — a pergunta "de quem veio esta
mercadoria?", que hoje não tem resposta.

O documento é opcional porque muita compra de bairro não tem nota no cadastro,
e exigir CNPJ para registrar o fornecedor da padaria da esquina inventaria uma
burocracia que a operação real não tem. Quando existe, ele é único no tenant:
dois cadastros do mesmo CNPJ são o mesmo fornecedor digitado duas vezes.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, Index, String, Text, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from app.core.db_types import EnumString


class SupplierStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Supplier(SQLModel, table=True):
    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "document", name="uq_tenant_supplier_document"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    #: O nome pelo qual a operação chama este fornecedor.
    name: str = Field(index=True, max_length=160)
    #: A razão social, quando ela difere do nome de uso.
    legal_name: Optional[str] = Field(default=None, max_length=200)
    #: CNPJ ou CPF, sem máscara. Opcional — ver o docstring do módulo.
    document: Optional[str] = Field(default=None, index=True, max_length=20)
    status: SupplierStatusEnum = Field(
        default=SupplierStatusEnum.ACTIVE,
        sa_column=Column(EnumString(SupplierStatusEnum), nullable=False, index=True),
    )
    notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SupplierContact(SQLModel, table=True):
    """Com quem se fala nesse fornecedor.

    Um fornecedor tem mais de um contato — o vendedor, o financeiro, o motorista
    que entrega — e guardar um telefone só no cadastro obriga a escolher qual
    deles cabe. Cada contato é uma linha, e um deles pode ser o principal.
    """

    __tablename__ = "supplier_contacts"
    __table_args__ = (
        # Um principal por fornecedor, e é o **banco** que garante. A rota
        # desmarcava os anteriores antes de inserir, o que basta em fila
        # única e não basta em duas requisições ao mesmo tempo: as duas leem,
        # as duas desmarcam, as duas inserem, e sobram dois principais — a
        # tela deixa de responder a quem ligar.
        Index(
            "uq_supplier_primary_contact", "supplier_id",
            unique=True, postgresql_where=text("is_primary"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    supplier_id: uuid.UUID = Field(foreign_key="suppliers.id", ondelete="CASCADE", index=True)
    name: str = Field(max_length=160)
    #: "Vendedor", "Financeiro", "Entregas" — a palavra de quem usa.
    role: Optional[str] = Field(default=None, max_length=80)
    email: Optional[str] = Field(default=None, sa_column=Column(String(254), nullable=True))
    phone: Optional[str] = Field(default=None, max_length=40)
    is_primary: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
