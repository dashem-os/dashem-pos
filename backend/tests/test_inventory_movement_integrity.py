"""Um movimento de estoque tem que dizer a verdade sobre o que fez com o saldo.

Três defeitos foram observados na homologação de 06/09/2026 e reproduzidos aqui
antes de qualquer correção:

1. **o tipo do movimento não decidia o efeito.** O serviço somava a quantidade
   recebida, qualquer que fosse o tipo. Registrar perda de 5 unidades
   *acrescentava* 5 ao saldo, e o movimento gravado dizia `LOSS · 5` numa linha
   em que o estoque subiu — o histórico mentia junto com o saldo;
2. **a baixa de venda não era uma transação só.** `adjust_stock` dava commit
   próprio e era chamado item a item, depois de a venda já ter sido marcada como
   paga. Falha no segundo item deixava a venda paga e o primeiro item baixado,
   com a requisição respondendo erro;
3. **quantidade assinada era aceita de qualquer cliente.** Um `POST` manual com
   `movement_type: SALE` se passava por baixa de venda.

A regra que fecha os três é a mesma: **o servidor deriva a variação assinada a
partir da operação**, o cliente informa magnitude, e quem coordena a operação
inteira é quem confirma a transação.

`ADJUSTMENT` é a exceção declarada: ele *é* a diferença assinada, é a operação
técnica restrita, e continua aceitando valor negativo. A contagem de estoque
cotidiana — que informa o total encontrado e deixa o servidor calcular a
diferença — é da etapa 2, e não existe ainda.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.api.v1.endpoints.inventory import StockAdjustDTO, adjust_stock_endpoint
from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.catalog import (
    InventoryBalance, InventoryMovement, MovementTypeEnum, Product,
)
from app.core.context import authorize_tenant_context
from app.core.security import AuthPrincipal
from app.models.identity import (
    AuthIdentity, Membership, MembershipStatusEnum, RoleEnum, Store, Tenant,
    TenantStatusEnum, User,
)
from app.models.platform import EntitlementStatusEnum, TenantCapability
from app.models.payment import Payment, PaymentMethodEnum, PaymentStatusEnum
from app.models.sale import Sale, SaleItem, SaleStatusEnum
from app.services import inventory_service, payment_service


def _session() -> Session:
    """Sessão de teste que não expira o objeto ao confirmar.

    Sem isto, ler `product.id` depois do bloco dispara recarga fora da sessão. É
    conveniência do harness e não afrouxa nenhuma prova: tudo o que precisa ser
    verificado como persistido é lido por uma sessão nova, aberta depois.
    """
    return Session(engine, expire_on_commit=False)


def _context(session: Session) -> TenantContext:
    """Um tenant com uma loja, e alguém autenticado para responder pelo movimento."""
    suffix = uuid.uuid4().hex[:8]
    set_platform_db_context(session)
    tenant = Tenant(
        name=f"Estoque {suffix}", slug=f"estoque-{suffix}", status=TenantStatusEnum.ACTIVE,
    )
    session.add(tenant)
    session.flush()
    store = Store(tenant_id=tenant.id, name="Matriz", code=f"EST-{suffix}")
    session.add(store)
    session.commit()
    context = TenantContext(
        tenant_id=tenant.id, store_id=store.id, user_id=uuid.uuid4(),
        auth_subject=f"gerente-{suffix}",
    )
    set_tenant_db_context(session, context.tenant_id, context.store_id, context.user_id)
    return context


def _product(session: Session, context: TenantContext, *, tracks: bool = True) -> uuid.UUID:
    """Devolve o id, não a linha.

    Um rollback expira os objetos da sessão, e ler `product.id` depois do bloco
    quebraria com `DetachedInstanceError` — que é ruído de harness em cima da
    falha que o teste quer mostrar.
    """
    suffix = uuid.uuid4().hex[:8]
    product = Product(
        tenant_id=context.tenant_id, name=f"Mercadoria {suffix}", sku=f"SKU-{suffix}",
        tracks_inventory=tracks,
    )
    session.add(product)
    session.commit()
    return product.id


def _stocked(session: Session, context: TenantContext, quantity: str) -> uuid.UUID:
    """Mercadoria com saldo, recebida pela mesma operação que o lojista usa."""
    product_id = _product(session, context)
    inventory_service.adjust_stock(
        session=session, context=context, store_id=context.store_id,
        product_id=product_id, actor_id=context.user_id,
        movement_type=MovementTypeEnum.PURCHASE, quantity=Decimal(quantity),
        reason="Recebimento inicial",
    )
    session.commit()
    return product_id


def _balance(tenant_id, store_id, product_id) -> Decimal:
    """O saldo como ele ficou gravado, lido por uma sessão nova.

    Uma sessão nova, e não `refresh`: o que importa é o que sobrevive ao fim da
    transação, não o que a sessão que escreveu ainda tem em memória.
    """
    with Session(engine) as session:
        set_tenant_db_context(session, tenant_id, store_id, None)
        row = session.exec(select(InventoryBalance).where(
            InventoryBalance.tenant_id == tenant_id,
            InventoryBalance.store_id == store_id,
            InventoryBalance.product_id == product_id,
        )).first()
        return Decimal("0") if row is None else Decimal(str(row.quantity))


# --------------------------------------------------------------- contrato do sinal

def test_a_loss_takes_goods_out_of_the_balance():
    """O defeito relatado: perda positiva aumentava o estoque."""
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")

        inventory_service.adjust_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            movement_type=MovementTypeEnum.LOSS, quantity=Decimal("3"),
            reason="Avaria no transporte",
        )
        session.commit()

    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("7.0000")


def test_a_receipt_and_a_return_add_to_the_balance():
    """Entradas continuam entradas: a correção não inverte o que já estava certo."""
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")

        for movement_type in (MovementTypeEnum.PURCHASE, MovementTypeEnum.RETURN):
            inventory_service.adjust_stock(
                session=session, context=context, store_id=context.store_id,
                product_id=product_id, actor_id=context.user_id,
                movement_type=movement_type, quantity=Decimal("2"),
                reason="Entrada",
            )
        session.commit()

    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("14.0000")


@pytest.mark.parametrize("movement_type", [
    MovementTypeEnum.PURCHASE, MovementTypeEnum.LOSS,
    MovementTypeEnum.RETURN, MovementTypeEnum.SALE,
])
def test_a_directional_movement_refuses_a_signed_quantity(movement_type):
    """Quem informa o sinal é a operação, não quem digita.

    Aceitar `-3` numa perda era ambíguo por construção: ou o cliente estava
    dizendo o efeito, ou estava dizendo a magnitude, e o serviço não tinha como
    distinguir. Recusar é o que resolve — inverter em silêncio manteria a
    ambiguidade e ainda esconderia o cliente que precisa ser corrigido.
    """
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")

        with pytest.raises(HTTPException) as refused:
            inventory_service.adjust_stock(
                session=session, context=context, store_id=context.store_id,
                product_id=product_id, actor_id=context.user_id,
                movement_type=movement_type, quantity=Decimal("-3"),
                reason="Quantidade assinada",
            )
        session.rollback()

    assert refused.value.status_code == 400
    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("10.0000")


@pytest.mark.parametrize("movement_type", list(MovementTypeEnum))
def test_a_movement_of_zero_is_refused(movement_type):
    """Movimento que não move nada é ruído no histórico, não fato."""
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")

        with pytest.raises(HTTPException) as refused:
            inventory_service.adjust_stock(
                session=session, context=context, store_id=context.store_id,
                product_id=product_id, actor_id=context.user_id,
                movement_type=movement_type, quantity=Decimal("0"),
                reason="Nada",
            )
        session.rollback()

    assert refused.value.status_code == 400


def test_a_technical_adjustment_is_the_one_operation_that_carries_its_own_sign():
    """`ADJUSTMENT` é a diferença assinada, e continua sendo."""
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")

        inventory_service.adjust_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            movement_type=MovementTypeEnum.ADJUSTMENT, quantity=Decimal("-2"),
            reason="Diferença apurada em conferência",
        )
        session.commit()

    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("8.0000")


def test_an_exit_larger_than_the_balance_is_refused_with_the_numbers_that_explain_it():
    """Não existe saldo negativo vendável, e a recusa precisa ser útil."""
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")

        with pytest.raises(HTTPException) as refused:
            inventory_service.adjust_stock(
                session=session, context=context, store_id=context.store_id,
                product_id=product_id, actor_id=context.user_id,
                movement_type=MovementTypeEnum.LOSS, quantity=Decimal("15"),
                reason="Perda maior que o saldo",
            )
        session.rollback()

    assert refused.value.status_code == 400
    assert "Disponível: 10" in refused.value.detail
    assert "solicitado: 15" in refused.value.detail
    assert "INSUFFICIENT_STOCK" not in refused.value.detail
    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("10.0000")


def test_the_ledger_arithmetic_holds_on_every_movement():
    """Saldo anterior + variação assinada = saldo posterior, sem exceção."""
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")
        for movement_type, quantity in (
            (MovementTypeEnum.LOSS, "3"),
            (MovementTypeEnum.PURCHASE, "5"),
            (MovementTypeEnum.ADJUSTMENT, "-1"),
        ):
            inventory_service.adjust_stock(
                session=session, context=context, store_id=context.store_id,
                product_id=product_id, actor_id=context.user_id,
                movement_type=movement_type, quantity=Decimal(quantity),
                reason="Movimento da série",
            )
        session.commit()

    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, None)
        movements = session.exec(select(InventoryMovement).where(
            InventoryMovement.product_id == product_id,
        ).order_by(InventoryMovement.created_at)).all()

    assert len(movements) == 4
    for movement in movements:
        assert movement.previous_balance + movement.quantity == movement.new_balance, (
            f"{movement.movement_type} quebrou a aritmética do livro"
        )
    assert movements[-1].new_balance == Decimal("11.0000")


# ------------------------------------------------------- operação que não é venda

def test_a_manual_movement_cannot_impersonate_a_sale():
    """Baixa de venda pertence ao fluxo de venda, e a rota manual recusa.

    A rota é onde a recusa cabe: o serviço continua sendo chamado com `SALE` por
    `payment_service`, que é o único caminho legítimo.
    """
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")

        with pytest.raises(HTTPException) as refused:
            adjust_stock_endpoint(
                data=StockAdjustDTO(
                    store_id=context.store_id, product_id=product_id,
                    actor_id=context.user_id, movement_type=MovementTypeEnum.SALE,
                    quantity=3.0, reason="Venda balcão",
                ),
                context=context, x_idempotency_key=None, x_correlation_id=None,
                session=session,
            )
        session.rollback()

    assert refused.value.status_code == 400
    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("10.0000")


def test_a_loss_through_the_route_reaches_the_balance_and_the_ledger_together():
    """A rota permanece o caminho do lojista, e agora com o efeito correto."""
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")

        response = adjust_stock_endpoint(
            data=StockAdjustDTO(
                store_id=context.store_id, product_id=product_id,
                actor_id=context.user_id, movement_type=MovementTypeEnum.LOSS,
                quantity=1.0, reason="Vencimento",
            ),
            context=context, x_idempotency_key=None, x_correlation_id=None,
            session=session,
        )

    assert Decimal(str(response["balance"]["quantity"])) == Decimal("9.0000")
    assert Decimal(str(response["movement"]["quantity"])) == Decimal("-1.0000")
    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("9.0000")


def test_the_same_movement_sent_twice_moves_the_stock_once():
    """Duplo clique, retry e timeout não podem cobrar duas vezes do saldo."""
    key = f"idem-{uuid.uuid4().hex[:10]}"
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")

        payload = StockAdjustDTO(
            store_id=context.store_id, product_id=product_id,
            actor_id=context.user_id, movement_type=MovementTypeEnum.LOSS,
            quantity=2.0, reason="Perda registrada uma vez",
        )
        first = adjust_stock_endpoint(
            data=payload, context=context, x_idempotency_key=key,
            x_correlation_id=None, session=session,
        )
        second = adjust_stock_endpoint(
            data=payload, context=context, x_idempotency_key=key,
            x_correlation_id=None, session=session,
        )

    assert str(first["movement"]["id"]) == str(second["movement"]["id"])
    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("8.0000")


# ------------------------------------------------------- a transação composta

def _sale_awaiting_payment(
    session: Session, context: TenantContext, items: list[tuple[uuid.UUID, str]],
    *, method: PaymentMethodEnum = PaymentMethodEnum.CASH,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Uma venda pronta para quitar, com os itens que ela vai baixar."""
    total = sum((Decimal(quantity) for _, quantity in items), Decimal("0"))
    sale = Sale(
        tenant_id=context.tenant_id, store_id=context.store_id,
        status=SaleStatusEnum.AWAITING_PAYMENT, seller_id=context.user_id,
        gross_total=total, net_total=total,
    )
    session.add(sale)
    session.flush()
    for product_id, quantity in items:
        product = session.get(Product, product_id)
        session.add(SaleItem(
            tenant_id=context.tenant_id, sale_id=sale.id, product_id=product_id,
            product_name=product.name, sku=product.sku,
            tracks_inventory_snapshot=True,
            unit_price=Decimal("1"), quantity=Decimal(quantity),
            gross_total=Decimal(quantity), net_total=Decimal(quantity),
        ))
    payment = Payment(
        tenant_id=context.tenant_id, store_id=context.store_id, sale_id=sale.id,
        method=method, status=PaymentStatusEnum.PENDING, amount=total,
    )
    session.add(payment)
    session.commit()
    return sale.id, payment.id


def test_a_paid_sale_takes_every_item_out_of_the_stock():
    """O caminho feliz, para que a correção da falha não o quebre."""
    with _session() as session:
        context = _context(session)
        first_id = _stocked(session, context, "10")
        second_id = _stocked(session, context, "10")
        sale_id, payment_id = _sale_awaiting_payment(session, context, [(first_id, "2"), (second_id, "3")])

        payment_service.confirm_payment(
            session=session, context=context, payment_id=payment_id,
            actor_id=context.user_id,
        )

    assert _balance(context.tenant_id, context.store_id, first_id) == Decimal("8.0000")
    assert _balance(context.tenant_id, context.store_id, second_id) == Decimal("7.0000")
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, None)
        assert session.get(Sale, sale_id).status == SaleStatusEnum.PAID


def test_a_failure_on_the_second_item_leaves_no_paid_sale_and_no_half_decrement():
    """A prova da falha transacional, lida numa sessão nova.

    A venda era marcada paga antes do laço, e o commit interno do primeiro item
    persistia essa marcação junto. A falta de estoque no segundo item derrubava a
    requisição com 400 — e deixava para trás uma venda paga com um item baixado e
    o outro não. Uma sessão nova é o que separa "a transação foi desfeita" de "a
    sessão que escreveu ainda não tinha visto".
    """
    with _session() as session:
        context = _context(session)
        available_id = _stocked(session, context, "10")
        empty_id = _product(session, context)
        sale_id, payment_id = _sale_awaiting_payment(
            session, context, [(available_id, "2"), (empty_id, "1")],
        )

        with pytest.raises(HTTPException) as refused:
            payment_service.confirm_payment(
                session=session, context=context, payment_id=payment_id,
                actor_id=context.user_id,
            )
        session.rollback()

    assert refused.value.status_code == 400

    assert _balance(context.tenant_id, context.store_id, available_id) == Decimal("10.0000"), (
        "o primeiro item continuou baixado depois do erro no segundo"
    )
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, None)
        persisted = session.get(Sale, sale_id)
        assert persisted.status == SaleStatusEnum.AWAITING_PAYMENT, (
            "a venda ficou paga apesar de a baixa de estoque ter falhado"
        )
        movements = session.exec(select(InventoryMovement).where(
            InventoryMovement.product_id == available_id,
            InventoryMovement.movement_type == MovementTypeEnum.SALE,
        )).all()
        assert movements == [], "sobrou movimento de venda de uma venda que não aconteceu"


def test_two_confirmations_do_not_sell_the_same_last_unit():
    """Duas sessões, uma unidade: a segunda é recusada, não vira saldo negativo."""
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "1")
        _, first_payment_id = _sale_awaiting_payment(session, context, [(product_id, "1")])
        _, second_payment_id = _sale_awaiting_payment(session, context, [(product_id, "1")])

    with _session() as first, _session() as second:
        set_tenant_db_context(first, context.tenant_id, context.store_id, context.user_id)
        set_tenant_db_context(second, context.tenant_id, context.store_id, context.user_id)

        payment_service.confirm_payment(
            session=first, context=context, payment_id=first_payment_id,
            actor_id=context.user_id,
        )
        with pytest.raises(HTTPException) as refused:
            payment_service.confirm_payment(
                session=second, context=context, payment_id=second_payment_id,
                actor_id=context.user_id,
            )
        second.rollback()

    assert refused.value.status_code == 400
    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("0.0000")


def test_an_item_that_does_not_track_inventory_moves_nothing():
    """Serviço não tem saldo físico, e continua sem criar movimento."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context, tracks=False)

        movement, balance, created = inventory_service.adjust_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            movement_type=MovementTypeEnum.PURCHASE, quantity=Decimal("5"),
            reason="Serviço não estoca",
        )

    assert created is False and movement is None
    assert Decimal(str(balance.quantity)) == Decimal("0.00")


# ---------------------------------------- retry, escopo, permissao e precisao

def test_confirming_the_same_payment_twice_takes_the_stock_out_once():
    """Retry de pagamento e chamada repetida apos timeout nao baixam duas vezes."""
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")
        sale_id, payment_id = _sale_awaiting_payment(session, context, [(product_id, "3")])

        payment_service.confirm_payment(
            session=session, context=context, payment_id=payment_id,
            actor_id=context.user_id,
        )
        payment_service.confirm_payment(
            session=session, context=context, payment_id=payment_id,
            actor_id=context.user_id,
        )

    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("7.0000")
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, None)
        movements = session.exec(select(InventoryMovement).where(
            InventoryMovement.product_id == product_id,
            InventoryMovement.movement_type == MovementTypeEnum.SALE,
        )).all()
    assert len(movements) == 1


def test_a_movement_aimed_at_another_store_is_refused():
    """A unidade ativa e a fronteira: ninguem movimenta o estoque de outra."""
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")

        with pytest.raises(HTTPException) as refused:
            inventory_service.adjust_stock(
                session=session, context=context, store_id=uuid.uuid4(),
                product_id=product_id, actor_id=context.user_id,
                movement_type=MovementTypeEnum.PURCHASE, quantity=Decimal("5"),
                reason="Loja alheia",
            )
        session.rollback()

    assert refused.value.status_code == 403
    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("10.0000")


def test_a_product_from_another_tenant_is_not_found():
    """O produto de outro inquilino nao existe para quem pede."""
    with _session() as session:
        outro = _context(session)
        alheio = _stocked(session, outro, "10")

    with _session() as session:
        context = _context(session)
        with pytest.raises(HTTPException) as refused:
            inventory_service.adjust_stock(
                session=session, context=context, store_id=context.store_id,
                product_id=alheio, actor_id=context.user_id,
                movement_type=MovementTypeEnum.PURCHASE, quantity=Decimal("5"),
                reason="Produto de outro tenant",
            )
        session.rollback()

    assert refused.value.status_code == 404
    assert _balance(outro.tenant_id, outro.store_id, alheio) == Decimal("10.0000")


def test_a_forged_actor_cannot_author_a_movement():
    """Quem assina o movimento e quem o servidor autenticou, e mais ninguem."""
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")

        with pytest.raises(HTTPException) as refused:
            inventory_service.adjust_stock(
                session=session, context=context, store_id=context.store_id,
                product_id=product_id, actor_id=uuid.uuid4(),
                movement_type=MovementTypeEnum.LOSS, quantity=Decimal("1"),
                reason="Ator forjado",
            )
        session.rollback()

    assert refused.value.status_code == 403
    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("10.0000")


def test_a_profile_without_the_permission_cannot_reach_the_route():
    """CASHIER le o estoque e nao o movimenta, pelo caminho autenticado."""
    suffix = uuid.uuid4().hex[:8]
    subject = str(uuid.uuid4())
    with _session() as session:
        set_platform_db_context(session)
        tenant = Tenant(
            name=f"Permissao {suffix}", slug=f"permissao-{suffix}",
            status=TenantStatusEnum.ACTIVE,
        )
        session.add(tenant)
        session.flush()
        store = Store(tenant_id=tenant.id, name="Matriz", code=f"PRM-{suffix}")
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
        leitura = authorize_tenant_context(
            session, principal, tenant_id, store_id, "GET", "/api/v1/inventory/movements",
        )
        assert "inventory.read" in leitura.permissions

        with pytest.raises(HTTPException) as refused:
            authorize_tenant_context(
                session, principal, tenant_id, store_id, "POST", "/api/v1/inventory/adjust",
            )
    assert refused.value.status_code == 403


def test_a_financial_refund_does_not_put_the_goods_back_on_the_shelf():
    """Devolver dinheiro nao e receber mercadoria de volta -- ADR-030.

    Sao dois fatos diferentes e independentes: o cliente pode ter o dinheiro de
    volta sem devolver o produto, e pode devolver o produto sem estorno. Repor
    estoque por conta de um movimento financeiro inventaria um fato fisico que
    ninguem observou.
    """
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")
        # PIX, e nao dinheiro: o ADR-030 exige caixa aberto para devolver em
        # especie, e o que esta em prova aqui e o estoque, nao a tesouraria.
        _, payment_id = _sale_awaiting_payment(
            session, context, [(product_id, "2")], method=PaymentMethodEnum.PIX,
        )
        payment_service.confirm_payment(
            session=session, context=context, payment_id=payment_id,
            actor_id=context.user_id,
        )
        payment_service.refund_payment(
            session=session, context=context, payment_id=payment_id,
            actor_id=context.user_id, amount=Decimal("2.00"),
            reason="Cliente desistiu do pagamento",
            idempotency_key=f"refund-{uuid.uuid4().hex[:10]}",
            cash_session_id=None, provider_reference=None,
        )

    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("8.0000"), (
        "o estorno financeiro repos mercadoria que ninguem devolveu"
    )


def test_a_physical_return_is_the_one_that_puts_the_goods_back():
    """A devolucao fisica e o outro fato, e ela sim mexe no saldo."""
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")
        _, payment_id = _sale_awaiting_payment(session, context, [(product_id, "2")])
        payment_service.confirm_payment(
            session=session, context=context, payment_id=payment_id,
            actor_id=context.user_id,
        )
        inventory_service.adjust_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            movement_type=MovementTypeEnum.RETURN, quantity=Decimal("2"),
            reason="Cliente devolveu a mercadoria",
        )
        session.commit()

    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("10.0000")


def test_a_fractional_item_keeps_every_decimal_it_was_given():
    """Peso e volume nao sao unidades inteiras, e arredondar e perder mercadoria."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        for movement_type, quantity in (
            (MovementTypeEnum.PURCHASE, "12.3456"),
            (MovementTypeEnum.LOSS, "0.1234"),
        ):
            inventory_service.adjust_stock(
                session=session, context=context, store_id=context.store_id,
                product_id=product_id, actor_id=context.user_id,
                movement_type=movement_type, quantity=Decimal(quantity),
                reason="Mercadoria fracionada",
            )
        session.commit()

    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("12.2222")


def test_changing_the_minimum_is_a_parameter_and_never_a_movement():
    """Definir quando repor nao e repor: o minimo nao gera entrada nem saida."""
    with _session() as session:
        context = _context(session)
        product_id = _stocked(session, context, "10")
        inventory_service.set_minimum_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, minimum_stock=Decimal("4"),
        )

    assert _balance(context.tenant_id, context.store_id, product_id) == Decimal("10.0000")
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, None)
        movements = session.exec(select(InventoryMovement).where(
            InventoryMovement.product_id == product_id,
        )).all()
        balance = session.exec(select(InventoryBalance).where(
            InventoryBalance.product_id == product_id,
        )).one()
    assert len(movements) == 1, "mudar o minimo criou movimento de estoque"
    assert Decimal(str(balance.minimum_stock)) == Decimal("4.0000")
