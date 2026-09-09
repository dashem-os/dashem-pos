"""Contas a pagar — lançar, consultar por vencimento, baixar, ajustar, reverter.

O contrato desta sprint está em `docs/product/ux-10-contas-a-pagar-contrato.md`
e é curto de propósito. O que ele **proíbe** está tão presente aqui quanto o que
ele pede:

* **nada cria dívida sozinho.** Não há gatilho de recebimento de mercadoria, e
  há teste que reprova se aparecer;
* **nada calcula juros, multa ou desconto.** Ajuste é valor digitado por uma
  pessoa, com motivo obrigatório. Regra de cálculo é decisão do dono;
* **não há parcelamento.** Um parcelamento é *N* obrigações com *N* vencimentos,
  e embutir isso numa conta só esconderia as datas que a operação precisa ver.

Toda escrita carrega `Idempotency-Key`, porque reenvio depois de erro de rede
não pode virar segunda conta nem segundo pagamento. Toda baixa carrega a
`version` que a pessoa tinha à vista, porque duas pessoas pagando a mesma conta
ao mesmo tempo não podem pagá-la duas vezes.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.context import TenantContext, get_tenant_context, resolve_actor, scope_tenant_query
from app.core.database import get_session
from app.models.payable import (
    Payable, PayableEntryTypeEnum, PayableLedgerEntry, PayableStatusEnum,
)
from app.models.supplier import Supplier
from app.services import reliability_service

router = APIRouter()

#: Dinheiro é decimal, e o arredondamento é o do centavo.
CENTAVO = Decimal("0.01")


class PayableWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: Vinculado ao cadastro da UX-09 quando é fornecedor. A conta de luz não
    #: tem fornecedor cadastrado e nem deveria precisar de um.
    supplier_id: Optional[uuid.UUID] = None
    payee_name: Optional[str] = PydanticField(default=None, max_length=160)
    store_id: Optional[uuid.UUID] = None
    description: Optional[str] = None
    amount: Decimal = PydanticField(gt=0, max_digits=14, decimal_places=4)
    due_on: date


class PayableUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payee_name: Optional[str] = PydanticField(default=None, max_length=160)
    supplier_id: Optional[uuid.UUID] = None
    description: Optional[str] = None
    due_on: Optional[date] = None


class SettleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal = PydanticField(gt=0, max_digits=14, decimal_places=4)
    occurred_on: Optional[date] = None
    method: Optional[str] = PydanticField(default=None, max_length=60)
    reason: Optional[str] = None
    #: A versão que a pessoa tinha à vista. Quem perde a corrida é recusado.
    version: int = PydanticField(ge=1)


class AdjustWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: Positivo acresce (juros, multa), negativo abate (desconto). O sistema
    #: não calcula nenhum dos dois: este número é digitado por uma pessoa.
    amount: Decimal = PydanticField(max_digits=14, decimal_places=4)
    reason: str = PydanticField(min_length=3)
    occurred_on: Optional[date] = None
    version: int = PydanticField(ge=1)


class ReverseWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_id: uuid.UUID
    reason: str = PydanticField(min_length=3)
    version: int = PydanticField(ge=1)


class ArchiveWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = PydanticField(min_length=3)
    version: int = PydanticField(ge=1)


class LedgerRead(BaseModel):
    id: uuid.UUID
    entry_type: PayableEntryTypeEnum
    amount: Decimal
    method: Optional[str] = None
    reason: Optional[str] = None
    reverses_entry_id: Optional[uuid.UUID] = None
    #: Preenchido no lançamento que **foi** revertido, para a tela conseguir
    #: mostrar "esta baixa foi desfeita" sem procurar na lista inteira.
    reversed_by_entry_id: Optional[uuid.UUID] = None
    occurred_on: date
    created_at: datetime


class PayableRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: Optional[uuid.UUID] = None
    supplier_id: Optional[uuid.UUID] = None
    payee_name: str
    description: Optional[str] = None
    status: PayableStatusEnum
    principal_amount: Decimal
    paid_amount: Decimal
    balance: Decimal
    due_on: date
    version: int
    archived_at: Optional[datetime] = None
    archived_reason: Optional[str] = None
    #: Derivada, nunca gravada: uma coluna "vencida" exigiria alguém virando
    #: linhas à meia-noite, e esse processo não existe.
    is_overdue: bool = False
    #: Negativo quando já venceu. Zero é "vence hoje".
    days_to_due: int = 0
    ledger: List[LedgerRead] = []


def _ler(session: Session, conta: Payable, com_razao: bool = True) -> PayableRead:
    hoje = date.today()
    em_aberto = conta.status in (PayableStatusEnum.OPEN, PayableStatusEnum.PARTIALLY_PAID)
    razao: List[LedgerRead] = []
    if com_razao:
        lancamentos = session.exec(
            select(PayableLedgerEntry)
            .where(PayableLedgerEntry.payable_id == conta.id)
            .order_by(PayableLedgerEntry.created_at)
        ).all()
        desfeito_por = {
            item.reverses_entry_id: item.id for item in lancamentos if item.reverses_entry_id
        }
        razao = [
            LedgerRead(
                id=item.id, entry_type=item.entry_type, amount=item.amount,
                method=item.method, reason=item.reason,
                reverses_entry_id=item.reverses_entry_id,
                reversed_by_entry_id=desfeito_por.get(item.id),
                occurred_on=item.occurred_on, created_at=item.created_at,
            )
            for item in lancamentos
        ]
    return PayableRead(
        id=conta.id, tenant_id=conta.tenant_id, store_id=conta.store_id,
        supplier_id=conta.supplier_id, payee_name=conta.payee_name,
        description=conta.description, status=conta.status,
        principal_amount=conta.principal_amount, paid_amount=conta.paid_amount,
        balance=conta.balance, due_on=conta.due_on, version=conta.version,
        archived_at=conta.archived_at, archived_reason=conta.archived_reason,
        is_overdue=em_aberto and conta.due_on < hoje,
        days_to_due=(conta.due_on - hoje).days,
        ledger=razao,
    )


def _alcanca(conta: Payable, context: TenantContext) -> bool:
    """A unidade aberta alcança esta conta?

    A regra é a mesma da listagem, e precisa ser a mesma: conta sem unidade é
    da empresa e todo mundo alcança; conta atribuída a uma unidade só é
    alcançada de dentro dela. Sem isto, a lista escondia a conta da outra
    unidade e a rota de baixa a aceitava mesmo assim — quem soubesse o
    identificador pagava a conta de uma loja estando em outra.
    """
    if conta.tenant_id != context.tenant_id:
        return False
    if context.store_id and conta.store_id and conta.store_id != context.store_id:
        return False
    return True


def _do_tenant(session: Session, context: TenantContext, payable_id: uuid.UUID) -> Payable:
    """Leitura. Não trava a linha — quem só olha não disputa nada."""
    conta = session.get(Payable, payable_id)
    if not conta or not _alcanca(conta, context):
        raise HTTPException(status_code=404, detail="Conta não encontrada.")
    return conta


def _travar(session: Session, context: TenantContext, payable_id: uuid.UUID) -> Payable:
    """A conta, travada no banco até o fim da transação.

    Conferir `version` em Python é ler e depois escrever: duas requisições leem
    a mesma versão, as duas passam pela conferência, e as duas gravam. A conta
    é paga duas vezes, e cada lançamento é válido sozinho — ninguém percebe.

    `FOR UPDATE` faz a segunda transação esperar a primeira. Quando ela
    finalmente lê, a versão já mudou, e a conferência recusa **com o saldo
    novo à vista**. É como o `receivable_service` — o espelho que este módulo
    diz seguir — já resolvia o mesmo problema.
    """
    conta = session.exec(
        select(Payable)
        .where(Payable.id == payable_id, Payable.tenant_id == context.tenant_id)
        .with_for_update()
    ).first()
    if not conta or not _alcanca(conta, context):
        raise HTTPException(status_code=404, detail="Conta não encontrada.")
    return conta


def _exigir_versao(conta: Payable, versao: int) -> None:
    """Quem perde a corrida é recusado **com o número atual à vista**.

    Dizer só "alguém alterou" manda a pessoa recarregar sem saber o que mudou.
    A frase abaixo diz o saldo, que é a informação que decide se ela ainda quer
    pagar o que ia pagar.
    """
    if conta.version != versao:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Esta conta mudou enquanto você olhava: o saldo agora é "
                f"R$ {conta.balance:.2f}. Confira antes de continuar."
            ),
        )


def _exigir_aberta(conta: Payable) -> None:
    if conta.status == PayableStatusEnum.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta conta foi arquivada. Ela não recebe mais lançamentos.",
        )


def _recalcular(session: Session, conta: Payable) -> None:
    """O saldo vem da razão, não de aritmética guardada em variável.

    Somar e subtrair no objeto funciona até o dia em que um caminho esquece de
    somar. Aqui o total é sempre relido dos lançamentos vivos — os revertidos
    saem da conta, e ambos continuam visíveis na tela.
    """
    lancamentos = session.exec(
        select(PayableLedgerEntry).where(PayableLedgerEntry.payable_id == conta.id)
    ).all()
    revertidos = {item.reverses_entry_id for item in lancamentos if item.reverses_entry_id}

    devido = Decimal("0")
    pago = Decimal("0")
    for item in lancamentos:
        if item.id in revertidos or item.entry_type == PayableEntryTypeEnum.REVERSAL:
            continue
        if item.entry_type == PayableEntryTypeEnum.PAYMENT:
            pago += -item.amount
        else:
            devido += item.amount

    conta.principal_amount = devido.quantize(CENTAVO)
    conta.paid_amount = pago.quantize(CENTAVO)
    conta.balance = (devido - pago).quantize(CENTAVO)
    if conta.status != PayableStatusEnum.ARCHIVED:
        if conta.balance <= 0:
            conta.status = PayableStatusEnum.PAID
        elif conta.paid_amount > 0:
            conta.status = PayableStatusEnum.PARTIALLY_PAID
        else:
            conta.status = PayableStatusEnum.OPEN
    conta.version += 1
    conta.updated_at = datetime.utcnow()
    session.add(conta)


def _registrar(
    session: Session, context: TenantContext, actor_id: uuid.UUID,
    conta: Payable, acao: str, dados: dict,
) -> None:
    """Auditoria e outbox de uma vez, com a mesma forma em todas as rotas."""
    reliability_service.write_audit_and_outbox(
        session, tenant_id=context.tenant_id, store_id=conta.store_id, actor_id=actor_id,
        action=acao, target=f"payable:{conta.id}", audit_payload=dados,
        aggregate_type="payable", aggregate_id=str(conta.id),
        event_type=acao, outbox_payload=dados,
    )


def _operacao(rota: str, payable_id: Optional[uuid.UUID] = None) -> str:
    """O nome da operação carrega a conta.

    Sem o identificador aqui, a mesma `Idempotency-Key` usada em **outra**
    conta batia no registro da primeira e devolvia a resposta dela: a segunda
    baixa não era gravada, e a tela mostrava sucesso. Perda silenciosa de
    pagamento — o pior defeito possível neste domínio.

    Com a conta no nome, cada conta tem o seu espaço de chaves, e o reenvio
    continua sendo reconhecido onde deve ser.
    """
    return f"POST /api/v1/payables/{payable_id}/{rota}" if payable_id else f"POST /api/v1/payables/{rota}"


def _chave_do_lancamento(payable_id: uuid.UUID, chave: str) -> str:
    """A chave gravada na razão também é da conta.

    `uq_tenant_payable_ledger_key` é única por tenant. Sem o identificador da
    conta, reusar a chave em outra conta bateria na restrição e viraria um 500
    — a mesma perda, com outra cara.
    """
    return f"{payable_id}:{chave}"


def _ja_registrado() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "Este lançamento já foi registrado nesta conta. "
            "Recarregue para ver como ela ficou."
        ),
    )


def _chave(x_idempotency_key: Optional[str]) -> str:
    if not x_idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta operação exige Idempotency-Key: dinheiro não se registra duas vezes.",
        )
    return x_idempotency_key


@router.get("", response_model=List[PayableRead])
def listar_contas(
    situacao: Optional[Literal["ABERTAS", "VENCIDAS", "PAGAS", "ARQUIVADAS", "TODAS"]] = "ABERTAS",
    vence_ate: Optional[date] = None,
    supplier_id: Optional[uuid.UUID] = None,
    busca: Optional[str] = Query(default=None, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    """A consulta que a operação faz é **por vencimento**, não por cadastro.

    O escopo **não** usa `scope_tenant_query` aqui, e é de propósito: aquele
    ajudante casa `store_id` com a unidade aberta, e a conta de luz — que é da
    empresa, com `store_id` nulo — desaparecia da lista assim que alguém
    entrava com uma unidade selecionada. Ou seja, a conta mais comum de todas
    era a que sumia.

    A regra certa é inclusiva: conta sem unidade é de todo mundo, e conta
    atribuída a uma unidade aparece nela.
    """
    consulta = select(Payable).where(Payable.tenant_id == context.tenant_id)
    if context.store_id:
        consulta = consulta.where(
            or_(Payable.store_id.is_(None), Payable.store_id == context.store_id)
        )
    abertas = (PayableStatusEnum.OPEN, PayableStatusEnum.PARTIALLY_PAID)
    if situacao == "ABERTAS":
        consulta = consulta.where(Payable.status.in_(abertas))
    elif situacao == "VENCIDAS":
        consulta = consulta.where(Payable.status.in_(abertas), Payable.due_on < date.today())
    elif situacao == "PAGAS":
        consulta = consulta.where(Payable.status == PayableStatusEnum.PAID)
    elif situacao == "ARQUIVADAS":
        consulta = consulta.where(Payable.status == PayableStatusEnum.ARCHIVED)
    if vence_ate:
        consulta = consulta.where(Payable.due_on <= vence_ate)
    if supplier_id:
        consulta = consulta.where(Payable.supplier_id == supplier_id)
    if busca:
        consulta = consulta.where(Payable.payee_name.ilike(f"%{busca.strip()}%"))
    contas = session.exec(consulta.order_by(Payable.due_on, Payable.payee_name)).all()
    # A razão não vai na lista: são muitas contas, e quem olha a lista está
    # decidindo o que pagar, não conferindo lançamento.
    return [_ler(session, item, com_razao=False) for item in contas]


@router.get("/{payable_id}", response_model=PayableRead)
def ver_conta(
    payable_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return _ler(session, _do_tenant(session, context, payable_id))


@router.post("", response_model=PayableRead, status_code=201)
def lancar_conta(
    data: PayableWrite,
    context: TenantContext = Depends(get_tenant_context),
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
):
    chave = _chave(x_idempotency_key)
    actor_id = resolve_actor(context)
    cacheado, codigo, corpo = reliability_service.check_idempotency(
        session=session, tenant_id=context.tenant_id, actor_id=actor_id,
        operation=_operacao("lancamentos"), idempotency_key=chave,
        request_payload=jsonable_encoder(data),
    )
    if cacheado and codigo and corpo:
        return corpo

    # O favorecido tem duas formas, e uma delas precisa existir.
    nome = (data.payee_name or "").strip()
    if data.supplier_id:
        fornecedor = session.exec(scope_tenant_query(
            select(Supplier).where(Supplier.id == data.supplier_id), Supplier, context,
        )).first()
        if not fornecedor:
            raise HTTPException(status_code=404, detail="Fornecedor não encontrado.")
        # O nome fica gravado mesmo vindo do cadastro: a conta precisa
        # continuar legível se o fornecedor for arquivado depois.
        nome = nome or fornecedor.name
    if not nome:
        raise HTTPException(
            status_code=422,
            detail="Diga para quem é a conta: escolha um fornecedor ou escreva o nome.",
        )

    conta = Payable(
        tenant_id=context.tenant_id, store_id=data.store_id, supplier_id=data.supplier_id,
        payee_name=nome, description=(data.description or "").strip() or None,
        principal_amount=data.amount, paid_amount=Decimal("0"), balance=data.amount,
        due_on=data.due_on, issue_idempotency_key=chave, created_by=actor_id,
    )
    session.add(conta)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta conta já foi lançada. Recarregue a lista para vê-la.",
        )

    session.add(PayableLedgerEntry(
        tenant_id=context.tenant_id, payable_id=conta.id,
        entry_type=PayableEntryTypeEnum.ISSUE, amount=data.amount,
        occurred_on=data.due_on, idempotency_key=f"{chave}:issue", created_by=actor_id,
    ))
    session.flush()

    _registrar(session, context, actor_id, conta, "tenant.payable.issued", {
        "payee_name": nome, "amount": str(data.amount),
        "due_on": data.due_on.isoformat(),
        "supplier_id": str(data.supplier_id) if data.supplier_id else None,
    })
    corpo = jsonable_encoder(_ler(session, conta))
    reliability_service.save_idempotency_record(
        session=session, tenant_id=context.tenant_id, actor_id=actor_id,
        operation=_operacao("lancamentos"), idempotency_key=chave,
        request_payload=jsonable_encoder(data), response_status=201, response_body=corpo,
    )
    session.commit()
    return corpo


@router.patch("/{payable_id}", response_model=PayableRead)
def editar_conta(
    payable_id: uuid.UUID,
    data: PayableUpdate,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    """Corrigir cadastro da conta. **O valor não se edita aqui**: mudar o valor
    de uma dívida é ajuste, que deixa rastro e pede motivo."""
    conta = _travar(session, context, payable_id)
    _exigir_aberta(conta)
    campos = data.model_dump(exclude_unset=True)
    if "supplier_id" in campos and campos["supplier_id"]:
        fornecedor = session.exec(scope_tenant_query(
            select(Supplier).where(Supplier.id == campos["supplier_id"]), Supplier, context,
        )).first()
        if not fornecedor:
            raise HTTPException(status_code=404, detail="Fornecedor não encontrado.")
    for chave_campo in ("payee_name", "description"):
        if chave_campo in campos and campos[chave_campo] is not None:
            campos[chave_campo] = campos[chave_campo].strip() or None
    if campos.get("payee_name") is None and "payee_name" in campos:
        raise HTTPException(status_code=422, detail="A conta precisa dizer para quem é.")
    for nome_campo, valor in campos.items():
        setattr(conta, nome_campo, valor)
    conta.version += 1
    conta.updated_at = datetime.utcnow()
    session.add(conta)
    session.commit()
    session.refresh(conta)
    return _ler(session, conta)


@router.post("/{payable_id}/baixas", response_model=PayableRead, status_code=201)
def dar_baixa(
    payable_id: uuid.UUID,
    data: SettleWrite,
    context: TenantContext = Depends(get_tenant_context),
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
):
    """Baixa manual, total ou parcial.

    Parcial entra na primeira entrega por razão de operação: pagar metade de uma
    conta é comum, e um sistema que só aceita baixa total obriga a pessoa a
    registrar como paga uma conta que não está — o dado passa a valer menos que
    o caderno que ele substituiu.
    """
    chave = _chave(x_idempotency_key)
    actor_id = resolve_actor(context)
    cacheado, codigo, corpo = reliability_service.check_idempotency(
        session=session, tenant_id=context.tenant_id, actor_id=actor_id,
        operation=_operacao("baixas", payable_id), idempotency_key=chave,
        request_payload=jsonable_encoder(data),
    )
    if cacheado and codigo and corpo:
        return corpo

    conta = _travar(session, context, payable_id)
    _exigir_aberta(conta)
    _exigir_versao(conta, data.version)
    if data.amount > conta.balance:
        raise HTTPException(
            status_code=422,
            detail=(
                f"O valor é maior que o saldo desta conta, que é "
                f"R$ {conta.balance:.2f}. Pagar a mais não é baixa."
            ),
        )

    session.add(PayableLedgerEntry(
        tenant_id=context.tenant_id, payable_id=conta.id,
        entry_type=PayableEntryTypeEnum.PAYMENT, amount=-data.amount,
        method=(data.method or "").strip() or None,
        reason=(data.reason or "").strip() or None,
        occurred_on=data.occurred_on or date.today(),
        idempotency_key=_chave_do_lancamento(conta.id, chave), created_by=actor_id,
    ))
    try:
        session.flush()
    except IntegrityError:
        # `uq_tenant_payable_ledger_key`: este mesmo carimbo já virou lançamento
        # nesta conta. É o reenvio chegando junto com o original, e gravar os
        # dois seria pagar duas vezes.
        session.rollback()
        raise _ja_registrado()
    _recalcular(session, conta)

    _registrar(session, context, actor_id, conta, "tenant.payable.settled", {
        "amount": str(data.amount), "method": data.method,
        "balance_after": str(conta.balance), "status": conta.status.value,
    })
    corpo = jsonable_encoder(_ler(session, conta))
    reliability_service.save_idempotency_record(
        session=session, tenant_id=context.tenant_id, actor_id=actor_id,
        operation=_operacao("baixas", payable_id), idempotency_key=chave,
        request_payload=jsonable_encoder(data), response_status=201, response_body=corpo,
    )
    session.commit()
    return corpo


@router.post("/{payable_id}/ajustes", response_model=PayableRead, status_code=201)
def ajustar_conta(
    payable_id: uuid.UUID,
    data: AdjustWrite,
    context: TenantContext = Depends(get_tenant_context),
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
):
    """Juros, multa ou abatimento — **digitados**, com motivo obrigatório.

    O sistema não calcula nenhum dos três. Regra de cálculo é decisão do dono, e
    escolher uma para desbloquear a sprint é exatamente como o número fica
    errado no bolso de alguém. Isto aqui é o registro de uma decisão humana, na
    mesma disciplina do ajuste técnico de estoque.
    """
    if data.amount == 0:
        raise HTTPException(status_code=422, detail="Um ajuste de zero não ajusta nada.")
    chave = _chave(x_idempotency_key)
    actor_id = resolve_actor(context)
    cacheado, codigo, corpo = reliability_service.check_idempotency(
        session=session, tenant_id=context.tenant_id, actor_id=actor_id,
        operation=_operacao("ajustes", payable_id), idempotency_key=chave,
        request_payload=jsonable_encoder(data),
    )
    if cacheado and codigo and corpo:
        return corpo

    conta = _travar(session, context, payable_id)
    _exigir_aberta(conta)
    _exigir_versao(conta, data.version)
    if conta.principal_amount + data.amount <= 0:
        raise HTTPException(
            status_code=422,
            detail="Um abatimento não pode zerar a dívida: para isso, dê baixa ou arquive.",
        )

    session.add(PayableLedgerEntry(
        tenant_id=context.tenant_id, payable_id=conta.id,
        entry_type=PayableEntryTypeEnum.ADJUSTMENT, amount=data.amount,
        reason=data.reason.strip(), occurred_on=data.occurred_on or date.today(),
        idempotency_key=_chave_do_lancamento(conta.id, chave), created_by=actor_id,
    ))
    try:
        session.flush()
    except IntegrityError:
        # `uq_tenant_payable_ledger_key`: este mesmo carimbo já virou lançamento
        # nesta conta. É o reenvio chegando junto com o original, e gravar os
        # dois seria pagar duas vezes.
        session.rollback()
        raise _ja_registrado()
    _recalcular(session, conta)

    _registrar(session, context, actor_id, conta, "tenant.payable.adjusted", {
        "amount": str(data.amount), "reason": data.reason,
        "balance_after": str(conta.balance),
    })
    corpo = jsonable_encoder(_ler(session, conta))
    reliability_service.save_idempotency_record(
        session=session, tenant_id=context.tenant_id, actor_id=actor_id,
        operation=_operacao("ajustes", payable_id), idempotency_key=chave,
        request_payload=jsonable_encoder(data), response_status=201, response_body=corpo,
    )
    session.commit()
    return corpo


@router.post("/{payable_id}/reversoes", response_model=PayableRead, status_code=201)
def reverter_baixa(
    payable_id: uuid.UUID,
    data: ReverseWrite,
    context: TenantContext = Depends(get_tenant_context),
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
):
    """Desfazer uma baixa registrada por engano. **Nada é apagado.**

    A reversão é outro lançamento, apontando para o primeiro, e a tela mostra os
    dois: quem confere precisa ver que houve um engano e que ele foi desfeito,
    não uma conta que sempre esteve certa.
    """
    chave = _chave(x_idempotency_key)
    actor_id = resolve_actor(context)
    cacheado, codigo, corpo = reliability_service.check_idempotency(
        session=session, tenant_id=context.tenant_id, actor_id=actor_id,
        operation=_operacao("reversoes", payable_id), idempotency_key=chave,
        request_payload=jsonable_encoder(data),
    )
    if cacheado and codigo and corpo:
        return corpo

    conta = _travar(session, context, payable_id)
    _exigir_aberta(conta)
    _exigir_versao(conta, data.version)

    alvo = session.get(PayableLedgerEntry, data.entry_id)
    if not alvo or alvo.payable_id != conta.id:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado nesta conta.")
    if alvo.entry_type not in (PayableEntryTypeEnum.PAYMENT, PayableEntryTypeEnum.ADJUSTMENT):
        raise HTTPException(
            status_code=422,
            detail="Só baixa e ajuste podem ser revertidos. O lançamento de abertura, não.",
        )

    session.add(PayableLedgerEntry(
        tenant_id=context.tenant_id, payable_id=conta.id,
        entry_type=PayableEntryTypeEnum.REVERSAL, amount=-alvo.amount,
        reason=data.reason.strip(), reverses_entry_id=alvo.id,
        occurred_on=date.today(), idempotency_key=_chave_do_lancamento(conta.id, chave), created_by=actor_id,
    ))
    try:
        session.flush()
    except IntegrityError:
        # `uq_payable_reversal_once`: dois cliques em "Reverter" devolveriam o
        # saldo duas vezes, e a conta passaria a dever mais do que devia.
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este lançamento já foi revertido. Recarregue a conta para ver como ela ficou.",
        )
    _recalcular(session, conta)

    _registrar(session, context, actor_id, conta, "tenant.payable.reversed", {
        "entry_id": str(alvo.id), "entry_type": alvo.entry_type.value,
        "amount": str(alvo.amount), "reason": data.reason,
        "balance_after": str(conta.balance),
    })
    corpo = jsonable_encoder(_ler(session, conta))
    reliability_service.save_idempotency_record(
        session=session, tenant_id=context.tenant_id, actor_id=actor_id,
        operation=_operacao("reversoes", payable_id), idempotency_key=chave,
        request_payload=jsonable_encoder(data), response_status=201, response_body=corpo,
    )
    session.commit()
    return corpo


@router.post("/{payable_id}/arquivamento", response_model=PayableRead)
def arquivar_conta(
    payable_id: uuid.UUID,
    data: ArchiveWrite,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    """Conta lançada por engano. Diferente de reverter pagamento, e não se
    confunde com ela: aqui a dívida nunca existiu.

    Uma conta que já teve baixa **não** se arquiva — houve dinheiro saindo, e
    apagar a obrigação deixaria o pagamento órfão. Reverta a baixa primeiro.
    """
    conta = _travar(session, context, payable_id)
    _exigir_aberta(conta)
    _exigir_versao(conta, data.version)
    if conta.paid_amount > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Esta conta já teve baixa. Reverta o pagamento antes de arquivar, "
                "para o dinheiro que saiu não ficar sem dono."
            ),
        )
    conta.status = PayableStatusEnum.ARCHIVED
    conta.archived_at = datetime.utcnow()
    conta.archived_reason = data.reason.strip()
    conta.version += 1
    conta.updated_at = datetime.utcnow()
    session.add(conta)
    _registrar(session, context, resolve_actor(context), conta,
               "tenant.payable.archived", {"reason": data.reason})
    session.commit()
    session.refresh(conta)
    return _ler(session, conta)
