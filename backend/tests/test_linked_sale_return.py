"""Devolver mercadoria é receber de volta o que saiu, e só até o que saiu.

`RETURN` existia como entrada de estoque solta: uma quantidade, um motivo em
texto livre, nenhum vínculo com a venda de onde a mercadoria tinha saído. Nada
impedia devolver dez unidades de um item vendido duas vezes, e mercadoria que
voltou quebrada somava saldo vendável igual à que ainda podia ser vendida.

O contrato que estes testes fixam, ponto a ponto:

1. **origem** — a devolução se liga à venda e ao item de onde a mercadoria saiu;
2. **teto** — o vendido menos o já devolvido, inclusive com duas solicitações
   simultâneas disputando o mesmo item;
3. **reenvio** — repetir a mesma solicitação não duplica entrada, e reaproveitar
   a chave com outro conteúdo é recusado;
4. **condição e destino** — mercadoria imprópria não volta ao saldo vendável;
5. **separação** — devolução física e estorno financeiro são fatos
   independentes, cada um com o seu vínculo e o seu histórico;
6. **autorização** — permissão, loja e tenant conferidos no servidor.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app.core.context import TenantContext, authorize_tenant_context
from app.core.database import engine
from app.core.permissions import route_requirement
from app.core.security import AuthPrincipal
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.catalog import (
    InventoryBalance, InventoryMovement, MovementTypeEnum, Product,
)
from app.models.identity import (
    AuthIdentity, Membership, MembershipStatusEnum, RoleEnum, Store, Tenant,
    TenantStatusEnum, User,
)
from app.models.payment import Payment, PaymentMethodEnum, PaymentStatusEnum
from app.models.platform import EntitlementStatusEnum, TenantCapability
from app.models.sale import (
    ReturnConditionEnum, ReturnDestinationEnum, Sale, SaleItem, SaleItemReturn,
    SaleStatusEnum,
)
from app.services import inventory_service, payment_service, sale_service


RESALEABLE = ReturnConditionEnum.RESALEABLE
UNFIT = ReturnConditionEnum.UNFIT
TO_STOCK = ReturnDestinationEnum.SELLABLE_STOCK
QUARANTINE = ReturnDestinationEnum.QUARANTINE
DISCARD = ReturnDestinationEnum.DISCARD


def _session() -> Session:
    return Session(engine, expire_on_commit=False)


def _context(session: Session) -> TenantContext:
    suffix = uuid.uuid4().hex[:8]
    set_platform_db_context(session)
    tenant = Tenant(
        name=f"Devolução {suffix}", slug=f"devolucao-{suffix}", status=TenantStatusEnum.ACTIVE,
    )
    session.add(tenant)
    session.flush()
    store = Store(tenant_id=tenant.id, name="Matriz", code=f"DEV-{suffix}")
    session.add(store)
    session.commit()
    context = TenantContext(
        tenant_id=tenant.id, store_id=store.id, user_id=uuid.uuid4(),
        auth_subject=f"balconista-{suffix}",
    )
    set_tenant_db_context(session, context.tenant_id, context.store_id, context.user_id)
    return context


def _sold(
    session: Session, context: TenantContext, *, stock: str = "10", quantity: str = "3",
    tracks: bool = True, method: PaymentMethodEnum = PaymentMethodEnum.PIX,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Uma venda quitada, com a mercadoria já baixada do estoque."""
    suffix = uuid.uuid4().hex[:8]
    product = Product(
        tenant_id=context.tenant_id, name=f"Mercadoria {suffix}", sku=f"DEV-{suffix}",
        tracks_inventory=tracks,
    )
    session.add(product)
    session.commit()
    if tracks:
        inventory_service.adjust_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product.id, actor_id=context.user_id,
            movement_type=MovementTypeEnum.PURCHASE, quantity=Decimal(stock),
            reason="Recebimento",
        )
        session.commit()

    total = Decimal(quantity)
    sale = Sale(
        tenant_id=context.tenant_id, store_id=context.store_id,
        status=SaleStatusEnum.AWAITING_PAYMENT, seller_id=context.user_id,
        gross_total=total, net_total=total,
    )
    session.add(sale)
    session.flush()
    item = SaleItem(
        tenant_id=context.tenant_id, sale_id=sale.id, product_id=product.id,
        product_name=product.name, sku=product.sku, tracks_inventory_snapshot=tracks,
        unit_price=Decimal("1"), quantity=total, gross_total=total, net_total=total,
    )
    session.add(item)
    payment = Payment(
        tenant_id=context.tenant_id, store_id=context.store_id, sale_id=sale.id,
        method=method, status=PaymentStatusEnum.PENDING, amount=total,
    )
    session.add(payment)
    session.commit()
    payment_service.confirm_payment(
        session=session, context=context, payment_id=payment.id, actor_id=context.user_id,
    )
    return item.id, product.id, payment.id


def _balance(context: TenantContext, product_id) -> Decimal:
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, None)
        row = session.exec(select(InventoryBalance).where(
            InventoryBalance.product_id == product_id,
        )).first()
        return Decimal("0") if row is None else Decimal(str(row.quantity))


def _returns(context: TenantContext, sale_item_id) -> list[SaleItemReturn]:
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, None)
        return session.exec(select(SaleItemReturn).where(
            SaleItemReturn.sale_item_id == sale_item_id,
        )).all()


def _key() -> str:
    return f"return-{uuid.uuid4().hex[:10]}"


# ------------------------------------------------------------------- 1. origem

def test_a_return_carries_the_sale_and_the_item_it_came_from():
    """Sem origem não há teto a respeitar nem história a contar."""
    with _session() as session:
        context = _context(session)
        item_id, product_id, _ = _sold(session, context, stock="10", quantity="3")

        record, movement = sale_service.return_sold_item(
            session=session, context=context, sale_item_id=item_id,
            actor_id=context.user_id, quantity=Decimal("2"),
            condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
        )
        session.commit()

    assert record.sale_item_id == item_id
    assert record.product_id == product_id
    assert record.sale_id is not None
    assert movement is not None and movement.movement_type is MovementTypeEnum.RETURN
    # Vendeu 3 sobre 10, devolveu 2: 7 + 2.
    assert _balance(context, product_id) == Decimal("9.0000")


def test_an_item_from_another_tenant_is_not_found():
    """O item de venda de outro inquilino não existe para quem pede."""
    with _session() as session:
        outro = _context(session)
        alheio, _, _ = _sold(session, outro, quantity="2")

    with _session() as session:
        context = _context(session)
        with pytest.raises(HTTPException) as refused:
            sale_service.return_sold_item(
                session=session, context=context, sale_item_id=alheio,
                actor_id=context.user_id, quantity=Decimal("1"),
                condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
            )
        session.rollback()

    assert refused.value.status_code == 404


def test_a_sale_from_another_store_is_not_found():
    """A unidade da venda de origem é conferida contra a unidade ativa.

    A recusa é `404`, e não `403`, porque o escopo de tenant e loja filtra a
    consulta: a venda de outra unidade não é encontrada. Isso é melhor do que
    uma proibição explícita, que confirmaria que ela existe em algum lugar.
    """
    with _session() as session:
        context = _context(session)
        item_id, _, _ = _sold(session, context, quantity="2")

        outra_unidade = TenantContext(
            tenant_id=context.tenant_id, store_id=uuid.uuid4(),
            user_id=context.user_id, auth_subject=context.auth_subject,
        )
        with pytest.raises(HTTPException) as refused:
            sale_service.return_sold_item(
                session=session, context=outra_unidade, sale_item_id=item_id,
                actor_id=context.user_id, quantity=Decimal("1"),
                condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
            )
        session.rollback()

    assert refused.value.status_code == 404


def test_an_open_sale_cannot_be_returned_into_existence():
    """Venda aberta não entregou mercadoria, e devolver ali criaria saldo do nada.

    Nada foi baixado do estoque enquanto a venda não foi quitada. Aceitar uma
    "devolução" desse item seria inventar mercadoria: a entrada aconteceria sem
    que nenhuma saída a tivesse precedido.
    """
    with _session() as session:
        context = _context(session)
        suffix = uuid.uuid4().hex[:8]
        product = Product(
            tenant_id=context.tenant_id, name=f"Aberta {suffix}", sku=f"ABE-{suffix}",
        )
        session.add(product)
        session.commit()
        product_id = product.id
        inventory_service.adjust_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            movement_type=MovementTypeEnum.PURCHASE, quantity=Decimal("10"),
            reason="Recebimento",
        )
        sale = Sale(
            tenant_id=context.tenant_id, store_id=context.store_id,
            status=SaleStatusEnum.AWAITING_PAYMENT, seller_id=context.user_id,
            gross_total=Decimal("2"), net_total=Decimal("2"),
        )
        session.add(sale)
        session.flush()
        item = SaleItem(
            tenant_id=context.tenant_id, sale_id=sale.id, product_id=product_id,
            product_name=product.name, sku=product.sku, unit_price=Decimal("1"),
            quantity=Decimal("2"), gross_total=Decimal("2"), net_total=Decimal("2"),
        )
        session.add(item)
        session.commit()
        item_id = item.id

        with pytest.raises(HTTPException) as refused:
            sale_service.return_sold_item(
                session=session, context=context, sale_item_id=item_id,
                actor_id=context.user_id, quantity=Decimal("1"),
                condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
            )
        session.rollback()

    assert refused.value.status_code == 409
    assert "ainda não entregou" in refused.value.detail
    assert _balance(context, product_id) == Decimal("10.0000")


def test_a_cancelled_sale_cannot_become_a_fictitious_return():
    """Cancelar antes da baixa não é devolver: nada saiu para poder voltar."""
    with _session() as session:
        context = _context(session)
        item_id, product_id, _ = _sold(session, context, stock="10", quantity="3")

        sale_item = session.get(SaleItem, item_id)
        sale = session.get(Sale, sale_item.sale_id)
        sale.status = SaleStatusEnum.CANCELED
        session.add(sale)
        session.commit()

        with pytest.raises(HTTPException) as refused:
            sale_service.return_sold_item(
                session=session, context=context, sale_item_id=item_id,
                actor_id=context.user_id, quantity=Decimal("1"),
                condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
            )
        session.rollback()

    assert refused.value.status_code == 409
    assert _balance(context, product_id) == Decimal("7.0000")


@pytest.mark.parametrize("situacao", [
    SaleStatusEnum.PAID, SaleStatusEnum.COMPLETED,
    SaleStatusEnum.PARTIALLY_REFUNDED, SaleStatusEnum.REFUNDED,
])
def test_a_sale_that_delivered_the_goods_accepts_the_return(situacao):
    """Estorno é fato financeiro: quem devolveu o dinheiro pode devolver o produto."""
    with _session() as session:
        context = _context(session)
        item_id, product_id, _ = _sold(session, context, stock="10", quantity="3")

        sale_item = session.get(SaleItem, item_id)
        sale = session.get(Sale, sale_item.sale_id)
        sale.status = situacao
        session.add(sale)
        session.commit()

        record, _ = sale_service.return_sold_item(
            session=session, context=context, sale_item_id=item_id,
            actor_id=context.user_id, quantity=Decimal("1"),
            condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
        )
        session.commit()

    assert record.quantity == Decimal("1.0000")
    assert _balance(context, product_id) == Decimal("8.0000")


# --------------------------------------------------------------------- 2. teto

def test_a_return_cannot_exceed_what_was_sold():
    """Devolver mais do que saiu criaria mercadoria do nada."""
    with _session() as session:
        context = _context(session)
        item_id, product_id, _ = _sold(session, context, stock="10", quantity="3")

        with pytest.raises(HTTPException) as refused:
            sale_service.return_sold_item(
                session=session, context=context, sale_item_id=item_id,
                actor_id=context.user_id, quantity=Decimal("4"),
                condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
            )
        session.rollback()

    assert refused.value.status_code == 400
    assert "Vendido: 3" in refused.value.detail
    assert "disponível para devolução: 3" in refused.value.detail
    assert _balance(context, product_id) == Decimal("7.0000")


def test_the_ceiling_counts_what_was_already_returned():
    """Duas devoluções parciais somam contra o mesmo teto."""
    with _session() as session:
        context = _context(session)
        item_id, product_id, _ = _sold(session, context, stock="10", quantity="3")

        for quantidade in ("2", "1"):
            sale_service.return_sold_item(
                session=session, context=context, sale_item_id=item_id,
                actor_id=context.user_id, quantity=Decimal(quantidade),
                condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
            )
            session.commit()

        with pytest.raises(HTTPException) as refused:
            sale_service.return_sold_item(
                session=session, context=context, sale_item_id=item_id,
                actor_id=context.user_id, quantity=Decimal("1"),
                condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
            )
        session.rollback()

    assert refused.value.status_code == 400
    assert "já devolvido: 3" in refused.value.detail
    assert _balance(context, product_id) == Decimal("10.0000")
    assert len(_returns(context, item_id)) == 2


def test_two_simultaneous_returns_cannot_both_take_the_last_unit():
    """O teto é apurado sob bloqueio do item, não sobre uma leitura solta.

    Sem travar o item de venda, duas solicitações simultâneas leriam o mesmo
    total já devolvido e passariam as duas — somando além do vendido.
    """
    with _session() as a:
        context = _context(a)
        item_id, product_id, _ = _sold(a, context, stock="10", quantity="1")

        sale_service.return_sold_item(
            session=a, context=context, sale_item_id=item_id,
            actor_id=context.user_id, quantity=Decimal("1"),
            condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
        )

        with Session(engine) as b:
            set_tenant_db_context(b, context.tenant_id, context.store_id, context.user_id)
            b.exec(text("SET lock_timeout = '750ms'"))
            with pytest.raises(DBAPIError) as bloqueada:
                sale_service.return_sold_item(
                    session=b, context=context, sale_item_id=item_id,
                    actor_id=context.user_id, quantity=Decimal("1"),
                    condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
                )
            b.rollback()
        assert "lock" in str(bloqueada.value).lower()
        a.commit()

    assert len(_returns(context, item_id)) == 1
    assert _balance(context, product_id) == Decimal("10.0000")


def test_the_one_that_waited_is_refused_by_the_ceiling_afterwards():
    """Bloquear adia; o teto é quem recusa. A segunda vê o total já atualizado."""
    with _session() as session:
        context = _context(session)
        item_id, product_id, _ = _sold(session, context, stock="10", quantity="1")

        sale_service.return_sold_item(
            session=session, context=context, sale_item_id=item_id,
            actor_id=context.user_id, quantity=Decimal("1"),
            condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
        )
        session.commit()

        with pytest.raises(HTTPException) as refused:
            sale_service.return_sold_item(
                session=session, context=context, sale_item_id=item_id,
                actor_id=context.user_id, quantity=Decimal("1"),
                condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
            )
        session.rollback()

    assert refused.value.status_code == 400
    assert _balance(context, product_id) == Decimal("10.0000")


# ------------------------------------------------------------------ 3. reenvio

def test_repeating_the_same_request_does_not_duplicate_the_entry():
    """Retry e duplo clique devolvem a mesma devolução, não uma segunda."""
    key = _key()
    with _session() as session:
        context = _context(session)
        item_id, product_id, _ = _sold(session, context, stock="10", quantity="3")

        primeira, _ = sale_service.return_sold_item(
            session=session, context=context, sale_item_id=item_id,
            actor_id=context.user_id, quantity=Decimal("2"),
            condition=RESALEABLE, destination=TO_STOCK, idempotency_key=key,
        )
        session.commit()
        segunda, _ = sale_service.return_sold_item(
            session=session, context=context, sale_item_id=item_id,
            actor_id=context.user_id, quantity=Decimal("2"),
            condition=RESALEABLE, destination=TO_STOCK, idempotency_key=key,
        )
        session.commit()

    assert primeira.id == segunda.id
    assert len(_returns(context, item_id)) == 1
    assert _balance(context, product_id) == Decimal("9.0000")


@pytest.mark.parametrize("alteracao", ["quantidade", "condição"])
def test_the_same_key_with_different_content_is_refused(alteracao):
    """Reaproveitar a chave é comando novo se passando por reenvio."""
    key = _key()
    with _session() as session:
        context = _context(session)
        item_id, _, _ = _sold(session, context, stock="10", quantity="3")

        sale_service.return_sold_item(
            session=session, context=context, sale_item_id=item_id,
            actor_id=context.user_id, quantity=Decimal("2"),
            condition=RESALEABLE, destination=TO_STOCK, idempotency_key=key,
        )
        session.commit()

        diferente = {
            "quantidade": {"quantity": Decimal("1")},
            "condição": {"condition": UNFIT, "destination": QUARANTINE},
        }[alteracao]
        pedido = {
            "quantity": Decimal("2"), "condition": RESALEABLE,
            "destination": TO_STOCK, **diferente,
        }
        with pytest.raises(HTTPException) as refused:
            sale_service.return_sold_item(
                session=session, context=context, sale_item_id=item_id,
                actor_id=context.user_id, idempotency_key=key, **pedido,
            )
        session.rollback()

    assert refused.value.status_code == 409
    assert "outro comando" in refused.value.detail
    assert len(_returns(context, item_id)) == 1


# ------------------------------------------------------- 4. condição e destino

def test_unfit_goods_do_not_come_back_to_the_sellable_balance():
    """A mercadoria voltou, e o saldo vendável não sobe por causa disso."""
    with _session() as session:
        context = _context(session)
        item_id, product_id, _ = _sold(session, context, stock="10", quantity="3")
        antes = _balance(context, product_id)

        record, movement = sale_service.return_sold_item(
            session=session, context=context, sale_item_id=item_id,
            actor_id=context.user_id, quantity=Decimal("2"),
            condition=UNFIT, destination=QUARANTINE, idempotency_key=_key(),
            reason="Embalagem violada",
        )
        session.commit()

    assert movement is None, "mercadoria imprópria virou saldo vendável"
    assert record.movement_id is None
    assert record.destination is QUARANTINE
    assert _balance(context, product_id) == antes
    # E continua registrada: ela existe fisicamente na loja.
    assert len(_returns(context, item_id)) == 1


def test_unfit_goods_still_count_against_the_ceiling():
    """O que voltou imprópria também saiu da venda, e não pode voltar duas vezes."""
    with _session() as session:
        context = _context(session)
        item_id, _, _ = _sold(session, context, stock="10", quantity="2")

        sale_service.return_sold_item(
            session=session, context=context, sale_item_id=item_id,
            actor_id=context.user_id, quantity=Decimal("2"),
            condition=UNFIT, destination=DISCARD, idempotency_key=_key(),
        )
        session.commit()

        with pytest.raises(HTTPException) as refused:
            sale_service.return_sold_item(
                session=session, context=context, sale_item_id=item_id,
                actor_id=context.user_id, quantity=Decimal("1"),
                condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
            )
        session.rollback()

    assert refused.value.status_code == 400


@pytest.mark.parametrize(("condition", "destination"), [
    (UNFIT, TO_STOCK),
    (RESALEABLE, QUARANTINE),
    (RESALEABLE, DISCARD),
])
def test_an_incoherent_condition_and_destination_are_refused(condition, destination):
    """Dizer que está boa e mandar para o descarte é payload ambíguo."""
    with _session() as session:
        context = _context(session)
        item_id, _, _ = _sold(session, context, quantity="2")

        with pytest.raises(HTTPException) as refused:
            sale_service.return_sold_item(
                session=session, context=context, sale_item_id=item_id,
                actor_id=context.user_id, quantity=Decimal("1"),
                condition=condition, destination=destination, idempotency_key=_key(),
            )
        session.rollback()

    assert refused.value.status_code == 400


# --------------------------------------------------------------- 5. separação

def test_a_physical_return_moves_no_money():
    """Trazer o produto de volta não devolve o pagamento."""
    with _session() as session:
        context = _context(session)
        item_id, _, payment_id = _sold(session, context, stock="10", quantity="3")

        sale_service.return_sold_item(
            session=session, context=context, sale_item_id=item_id,
            actor_id=context.user_id, quantity=Decimal("3"),
            condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
        )
        session.commit()

    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, None)
        payment = session.get(Payment, payment_id)
    assert payment.status is PaymentStatusEnum.CONFIRMED, (
        "a devolução física estornou o pagamento por conta própria"
    )


def test_a_financial_refund_creates_no_return_and_no_stock_entry():
    """Devolver o dinheiro não traz o produto de volta — ADR-030."""
    with _session() as session:
        context = _context(session)
        item_id, product_id, payment_id = _sold(session, context, stock="10", quantity="3")
        antes = _balance(context, product_id)

        payment_service.refund_payment(
            session=session, context=context, payment_id=payment_id,
            actor_id=context.user_id, amount=Decimal("3.00"),
            reason="Cliente desistiu", idempotency_key=f"refund-{uuid.uuid4().hex[:10]}",
            cash_session_id=None, provider_reference=None,
        )
        session.commit()

    assert _balance(context, product_id) == antes
    assert _returns(context, item_id) == []


def test_both_facts_can_coexist_each_with_its_own_trail():
    """Estornar e devolver são independentes, e os dois deixam rastro próprio."""
    with _session() as session:
        context = _context(session)
        item_id, product_id, payment_id = _sold(session, context, stock="10", quantity="3")

        payment_service.refund_payment(
            session=session, context=context, payment_id=payment_id,
            actor_id=context.user_id, amount=Decimal("3.00"),
            reason="Cliente desistiu", idempotency_key=f"refund-{uuid.uuid4().hex[:10]}",
            cash_session_id=None, provider_reference=None,
        )
        record, movement = sale_service.return_sold_item(
            session=session, context=context, sale_item_id=item_id,
            actor_id=context.user_id, quantity=Decimal("3"),
            condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
        )
        session.commit()

    assert record.movement_id == movement.id
    assert _balance(context, product_id) == Decimal("10.0000")


def test_a_service_line_records_the_return_without_touching_stock():
    """Serviço não tem prateleira, e a devolução dele não inventa uma."""
    with _session() as session:
        context = _context(session)
        item_id, product_id, _ = _sold(session, context, quantity="1", tracks=False)

        record, movement = sale_service.return_sold_item(
            session=session, context=context, sale_item_id=item_id,
            actor_id=context.user_id, quantity=Decimal("1"),
            condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
        )
        session.commit()

    assert movement is None
    assert record.quantity == Decimal("1.0000")
    assert _balance(context, product_id) == Decimal("0")


# ------------------------------------------------------------- 6. autorização

def test_the_return_route_asks_for_the_permission_to_move_stock():
    """Receber devolução é movimentar estoque, e responde pela mesma autoridade."""
    assert route_requirement(
        "POST", "/api/v1/sales/returns",
    ).permission == "inventory.adjust"


def test_a_cashier_cannot_reach_the_return_route():
    """Medido pelo caminho autenticado, não pela intenção do texto."""
    suffix = uuid.uuid4().hex[:8]
    subject = str(uuid.uuid4())
    with _session() as session:
        set_platform_db_context(session)
        tenant = Tenant(
            name=f"Papel {suffix}", slug=f"papel-{suffix}", status=TenantStatusEnum.ACTIVE,
        )
        session.add(tenant)
        session.flush()
        store = Store(tenant_id=tenant.id, name="Matriz", code=f"PAP-{suffix}")
        session.add(store)
        user = User(email=f"caixa-{suffix}@example.test", full_name="Caixa")
        session.add(user)
        session.flush()
        session.add(AuthIdentity(
            user_id=user.id, provider="supabase", provider_subject=subject,
        ))
        session.add(Membership(
            user_id=user.id, tenant_id=tenant.id, store_id=None,
            role=RoleEnum.CASHIER, status=MembershipStatusEnum.ACTIVE,
        ))
        for key in ("catalog", "inventory", "payments"):
            session.add(TenantCapability(
                tenant_id=tenant.id, key=key, enabled=True,
                status=EntitlementStatusEnum.ACTIVE,
            ))
        session.commit()
        tenant_id, store_id = tenant.id, store.id

    principal = AuthPrincipal(
        subject=subject, email=f"caixa-{suffix}@example.test",
        session_id=str(uuid.uuid4()), assurance_level="aal1", claims={"sub": subject},
    )
    with Session(engine) as session:
        set_platform_db_context(session)
        with pytest.raises(HTTPException) as refused:
            authorize_tenant_context(
                session, principal, tenant_id, store_id, "POST", "/api/v1/sales/returns",
            )
    assert refused.value.status_code == 403


def test_a_forged_actor_cannot_author_a_return():
    """Quem assina a devolução é quem o servidor autenticou."""
    with _session() as session:
        context = _context(session)
        item_id, _, _ = _sold(session, context, quantity="2")

        with pytest.raises(HTTPException) as refused:
            sale_service.return_sold_item(
                session=session, context=context, sale_item_id=item_id,
                actor_id=uuid.uuid4(), quantity=Decimal("1"),
                condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
            )
        session.rollback()

    assert refused.value.status_code == 403


def test_a_return_beyond_the_stored_precision_is_refused():
    """A mesma régua de precisão da movimentação e da contagem."""
    with _session() as session:
        context = _context(session)
        item_id, _, _ = _sold(session, context, quantity="3")

        with pytest.raises(HTTPException) as refused:
            sale_service.return_sold_item(
                session=session, context=context, sale_item_id=item_id,
                actor_id=context.user_id, quantity=Decimal("1.00005"),
                condition=RESALEABLE, destination=TO_STOCK, idempotency_key=_key(),
            )
        session.rollback()

    assert refused.value.status_code == 400
    assert "quatro casas" in refused.value.detail
