"""Quem fornece a mercadoria — cadastro, contatos e o vínculo do recebimento.

**Não há pedido de compra aqui.** O enunciado da UX-09 proíbe inventá-lo como
entregue, e nenhuma rota abaixo finge que ele existe. O que existe é o cadastro
de quem fornece, com quem se fala lá dentro, e a resposta para "de quem veio
esta mercadoria?".

Criar carrega `Idempotency-Key`: o aceite pede cadastrar "sem duplicação no
retry", e um cadastro reenviado depois de um erro de rede não pode virar dois
fornecedores com o mesmo nome.
"""

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.context import TenantContext, get_tenant_context, resolve_actor, scope_tenant_query
from app.core.database import get_session
from app.models.catalog import InventoryMovement
from app.models.supplier import Supplier, SupplierContact, SupplierStatusEnum
from app.services import reliability_service

router = APIRouter()


class ContactWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = PydanticField(min_length=2, max_length=160)
    role: Optional[str] = PydanticField(default=None, max_length=80)
    email: Optional[str] = PydanticField(default=None, max_length=254)
    phone: Optional[str] = PydanticField(default=None, max_length=40)
    is_primary: bool = False


class ContactRead(ContactWrite):
    id: uuid.UUID
    supplier_id: uuid.UUID


class SupplierWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = PydanticField(min_length=2, max_length=160)
    legal_name: Optional[str] = PydanticField(default=None, max_length=200)
    document: Optional[str] = PydanticField(default=None, max_length=20)
    notes: Optional[str] = None


class SupplierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = PydanticField(default=None, min_length=2, max_length=160)
    legal_name: Optional[str] = PydanticField(default=None, max_length=200)
    document: Optional[str] = PydanticField(default=None, max_length=20)
    notes: Optional[str] = None
    status: Optional[SupplierStatusEnum] = None


class SupplierRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    legal_name: Optional[str] = None
    document: Optional[str] = None
    status: SupplierStatusEnum
    notes: Optional[str] = None
    contacts: List[ContactRead] = []
    #: Quantos recebimentos já foram atribuídos a ele. Zero é uma resposta.
    recebimentos: int = 0


def _sem_mascara(documento: Optional[str]) -> Optional[str]:
    """O documento sem máscara, e **com as letras que ele tiver**.

    O CNPJ alfanumérico entrou em operação em julho de 2026: as doze primeiras
    posições podem ser letras ou dígitos, e só os dois dígitos verificadores
    são numéricos. Uma normalização que guardava apenas dígitos apagava parte
    do documento e gravava outro no lugar — silenciosamente, porque o resultado
    ainda parecia um número.

    Então aqui se remove **apenas** a máscara, e o que sobra é normalizado em
    maiúsculas para "a1b2" e "A1B2" serem o mesmo documento na comparação.
    CPF continua funcionando pelo mesmo caminho: ele simplesmente não tem
    letras para preservar.
    """
    if documento is None:
        return None
    limpo = "".join(
        caractere for caractere in documento.upper()
        if caractere.isalnum()
    )
    return limpo or None


def _vazio_e_nada(valor: Optional[str]) -> Optional[str]:
    """Apagar o campo na tela apaga o campo no cadastro.

    A tela envia string vazia quando a pessoa seleciona o texto e apaga. Guardar
    `""` deixaria o cadastro com uma razão social que existe e não diz nada, e
    pior: um documento vazio entraria na regra de unicidade como se fosse um
    documento. Vazio aqui quer dizer *não tenho*, que é `None`.
    """
    if valor is None:
        return None
    limpo = valor.strip()
    return limpo or None


def _documento_de_outro(
    session: Session, context: TenantContext, documento: str, exceto: Optional[uuid.UUID] = None,
) -> Optional[Supplier]:
    consulta = scope_tenant_query(
        select(Supplier).where(Supplier.document == documento), Supplier, context,
    )
    if exceto:
        consulta = consulta.where(Supplier.id != exceto)
    return session.exec(consulta).first()


def _conflito_de_documento(documento: Optional[str], nome: Optional[str] = None) -> HTTPException:
    de_quem = f": {nome}." if nome else " neste cadastro."
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"Já existe um fornecedor com este documento{de_quem}",
    )


def _ler(session: Session, fornecedor: Supplier) -> SupplierRead:
    contatos = session.exec(
        select(SupplierContact)
        .where(SupplierContact.supplier_id == fornecedor.id)
        .order_by(SupplierContact.is_primary.desc(), SupplierContact.name)
    ).all()
    recebimentos = len(session.exec(
        select(InventoryMovement.id).where(InventoryMovement.supplier_id == fornecedor.id)
    ).all())
    return SupplierRead(
        id=fornecedor.id, tenant_id=fornecedor.tenant_id, name=fornecedor.name,
        legal_name=fornecedor.legal_name, document=fornecedor.document,
        status=fornecedor.status, notes=fornecedor.notes,
        contacts=[
            ContactRead(
                id=c.id, supplier_id=c.supplier_id, name=c.name, role=c.role,
                email=c.email, phone=c.phone, is_primary=c.is_primary,
            )
            for c in contatos
        ],
        recebimentos=recebimentos,
    )


def _do_tenant(session: Session, context: TenantContext, supplier_id: uuid.UUID) -> Supplier:
    fornecedor = session.get(Supplier, supplier_id)
    if not fornecedor or fornecedor.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado.")
    return fornecedor


@router.get("", response_model=List[SupplierRead])
def listar_fornecedores(
    busca: Optional[str] = Query(default=None, max_length=160),
    incluir_inativos: bool = False,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    consulta = scope_tenant_query(select(Supplier), Supplier, context)
    if not incluir_inativos:
        consulta = consulta.where(Supplier.status == SupplierStatusEnum.ACTIVE)
    if busca:
        agulha = f"%{busca.strip().lower()}%"
        digitos = _sem_mascara(busca)
        alvos = [Supplier.name.ilike(agulha)]
        if digitos:
            alvos.append(Supplier.document.ilike(f"%{digitos}%"))
        consulta = consulta.where(or_(*alvos))
    return [_ler(session, item) for item in session.exec(consulta.order_by(Supplier.name)).all()]


@router.post("", response_model=SupplierRead, status_code=201)
def cadastrar_fornecedor(
    data: SupplierWrite,
    context: TenantContext = Depends(get_tenant_context),
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
):
    actor_id = resolve_actor(context)
    if x_idempotency_key:
        cacheado, codigo, corpo = reliability_service.check_idempotency(
            session=session, tenant_id=context.tenant_id, actor_id=actor_id,
            operation="POST /api/v1/suppliers", idempotency_key=x_idempotency_key,
            request_payload=data.model_dump(),
        )
        if cacheado and codigo and corpo:
            return corpo

    documento = _sem_mascara(data.document)
    if documento:
        existente = _documento_de_outro(session, context, documento)
        if existente:
            raise _conflito_de_documento(documento, existente.name)

    fornecedor = Supplier(
        tenant_id=context.tenant_id, name=data.name.strip(),
        legal_name=_vazio_e_nada(data.legal_name),
        document=documento, notes=_vazio_e_nada(data.notes),
    )
    session.add(fornecedor)
    try:
        session.flush()
    except IntegrityError:
        # A consulta acima não viu ninguém, e mesmo assim o banco recusou:
        # outra requisição gravou o mesmo documento entre a leitura e a
        # gravação. É o mesmo conflito, e a pessoa merece a mesma frase.
        session.rollback()
        raise _conflito_de_documento(documento)
    corpo = jsonable_encoder(_ler(session, fornecedor))
    if x_idempotency_key:
        reliability_service.save_idempotency_record(
            session=session, tenant_id=context.tenant_id, actor_id=actor_id,
            operation="POST /api/v1/suppliers", idempotency_key=x_idempotency_key,
            request_payload=data.model_dump(), response_status=201, response_body=corpo,
        )
    session.commit()
    return corpo


@router.patch("/{supplier_id}", response_model=SupplierRead)
def editar_fornecedor(
    supplier_id: uuid.UUID,
    data: SupplierUpdate,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    fornecedor = _do_tenant(session, context, supplier_id)
    # `exclude_unset` é o que separa "não mexi neste campo" de "apaguei este
    # campo": só chega aqui o que a tela mandou, e o que ela mandou como nulo
    # ou vazio é para apagar.
    campos = data.model_dump(exclude_unset=True)
    if "document" in campos:
        campos["document"] = _sem_mascara(campos["document"])
        if campos["document"]:
            # Editar tem a mesma regra de cadastrar. Não tinha, e trocar o
            # documento de um fornecedor para o de outro passava direto até o
            # banco recusar com um erro que a tela não sabia explicar.
            outro = _documento_de_outro(
                session, context, campos["document"], exceto=fornecedor.id,
            )
            if outro:
                raise _conflito_de_documento(campos["document"], outro.name)
    for chave in ("legal_name", "notes"):
        if chave in campos:
            campos[chave] = _vazio_e_nada(campos[chave])
    if "name" in campos and campos["name"]:
        campos["name"] = campos["name"].strip()
    for chave, valor in campos.items():
        setattr(fornecedor, chave, valor)
    fornecedor.updated_at = datetime.utcnow()
    session.add(fornecedor)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise _conflito_de_documento(campos.get("document"))
    session.refresh(fornecedor)
    return _ler(session, fornecedor)


@router.post("/{supplier_id}/contatos", response_model=SupplierRead, status_code=201)
def adicionar_contato(
    supplier_id: uuid.UUID,
    data: ContactWrite,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    fornecedor = _do_tenant(session, context, supplier_id)
    if data.is_primary:
        # Um principal por fornecedor: dois "principais" não dizem a quem ligar.
        for outro in session.exec(select(SupplierContact).where(
            SupplierContact.supplier_id == fornecedor.id,
            SupplierContact.is_primary.is_(True),
        )).all():
            outro.is_primary = False
            session.add(outro)
        # A desmarcação vai ao banco **antes** da inserção. Sem isto a ordem
        # fica por conta do unit of work do SQLAlchemy, e um INSERT que chegue
        # antes do UPDATE bate no índice único e recusa a própria operação.
        session.flush()
    session.add(SupplierContact(
        tenant_id=context.tenant_id, supplier_id=fornecedor.id, name=data.name.strip(),
        role=_vazio_e_nada(data.role), email=_vazio_e_nada(data.email),
        phone=_vazio_e_nada(data.phone), is_primary=data.is_primary,
    ))
    try:
        session.commit()
    except IntegrityError:
        # `uq_supplier_primary_contact`: outra pessoa marcou o principal deste
        # fornecedor no mesmo instante. Recusar é melhor do que gravar o
        # segundo principal e deixar a tela sem resposta para "a quem ligar".
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Outra pessoa acabou de definir o contato principal deste "
                "fornecedor. Abra os contatos de novo para ver quem ficou."
            ),
        )
    session.refresh(fornecedor)
    return _ler(session, fornecedor)


@router.delete("/{supplier_id}/contatos/{contact_id}", response_model=SupplierRead)
def remover_contato(
    supplier_id: uuid.UUID,
    contact_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    fornecedor = _do_tenant(session, context, supplier_id)
    contato = session.get(SupplierContact, contact_id)
    if not contato or contato.supplier_id != fornecedor.id:
        raise HTTPException(status_code=404, detail="Contato não encontrado.")
    session.delete(contato)
    session.commit()
    session.refresh(fornecedor)
    return _ler(session, fornecedor)
