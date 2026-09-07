import uuid
from decimal import Decimal
from datetime import datetime
from typing import List, Optional, Tuple, Union
from sqlmodel import Session, select, text
from fastapi import HTTPException, status
from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.catalog import Product, InventoryMovement, InventoryBalance, MovementTypeEnum
from app.services import reliability_service

# Cada tipo de movimento tem uma direção, e é ela que decide o efeito no saldo.
# Antes o serviço somava a quantidade recebida qualquer que fosse o tipo, e quem
# informava o sinal era quem chamava — de modo que registrar perda de 5 unidades
# acrescentava 5 ao estoque, com o movimento gravado dizendo `LOSS · 5` numa
# linha em que o saldo subiu. O livro mentia junto com o saldo.
INCOMING_MOVEMENTS = frozenset({MovementTypeEnum.PURCHASE, MovementTypeEnum.RETURN})
OUTGOING_MOVEMENTS = frozenset({MovementTypeEnum.SALE, MovementTypeEnum.LOSS})


def signed_variation(
    movement_type: MovementTypeEnum, quantity: Union[float, Decimal],
) -> Decimal:
    """A variação assinada que esta operação aplica ao saldo.

    `ADJUSTMENT` é a única operação que carrega o próprio sinal: ela *é* a
    diferença apurada, e é a operação técnica restrita. Todas as outras recebem
    magnitude e têm a direção decidida aqui.

    Quantidade assinada numa operação direcional é recusada em vez de invertida.
    Inverter em silêncio manteria a ambiguidade — não há como saber se quem
    mandou `-3` numa perda estava dizendo o efeito ou a magnitude — e ainda
    esconderia o cliente que precisa ser corrigido.
    """
    variation = Decimal(str(quantity))
    if not variation.is_finite():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quantidade inválida: informe um número finito.",
        )
    if variation == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quantidade zero não movimenta estoque e não gera movimento.",
        )
    if movement_type in INCOMING_MOVEMENTS or movement_type in OUTGOING_MOVEMENTS:
        if variation < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Informe a quantidade positiva: a operação é que define "
                    "entrada ou saída de estoque."
                ),
            )
        return variation if movement_type in INCOMING_MOVEMENTS else -variation
    return variation


def adjust_stock(
    session: Session,
    context: TenantContext,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    actor_id: uuid.UUID,
    movement_type: MovementTypeEnum,
    quantity: Union[float, Decimal],
    reason: Optional[str] = None,
    correlation_id: Optional[str] = None
) -> Tuple[Optional[InventoryMovement], InventoryBalance, bool]:
    actor_id = resolve_actor(context, actor_id)
    qty_dec = signed_variation(movement_type, quantity)

    if context.store_id and store_id != context.store_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Movimentação fora da unidade ativa.")

    # 1. Verify Product exists and belongs to tenant
    product_query = select(Product).where(Product.id == product_id)
    product_query = scope_tenant_query(product_query, Product, context)
    product = session.exec(product_query).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product '{product_id}' not found for this tenant."
        )

    # 2. Check invariant: If item does NOT track inventory (e.g. Service), bypass movement
    if not product.tracks_inventory:
        balance_query = select(InventoryBalance).where(
            InventoryBalance.store_id == store_id,
            InventoryBalance.product_id == product_id
        )
        balance_query = scope_tenant_query(balance_query, InventoryBalance, context)
        balance = session.exec(balance_query).first()
        if not balance:
            balance = InventoryBalance(
                tenant_id=context.tenant_id,
                store_id=store_id,
                product_id=product_id,
                quantity=Decimal("0.00")
            )
        return None, balance, False

    # 3. ATOMIC POSTGRESQL UPSERT: Handles first-balance creation & concurrent updates with zero race conditions
    now = datetime.utcnow()
    upsert_query = text("""
        INSERT INTO inventory_balances (id, tenant_id, store_id, product_id, quantity, minimum_stock, updated_at)
        VALUES (:id, :tenant_id, :store_id, :product_id, :quantity, 0.0, :now)
        ON CONFLICT (tenant_id, store_id, product_id) DO UPDATE
        SET quantity = inventory_balances.quantity + EXCLUDED.quantity,
            updated_at = :now
        RETURNING inventory_balances.quantity AS new_balance;
    """)

    result = session.exec(upsert_query, params={
        "id": str(uuid.uuid4()),
        "tenant_id": str(context.tenant_id),
        "store_id": str(store_id),
        "product_id": str(product_id),
        # `Decimal`, não `float`. A linha acima monta `qty_dec` justamente para
        # não perder precisão, e converter aqui jogaria esse cuidado fora na
        # borda do banco — a coluna é `Numeric(14,4)` e psycopg2 adapta Decimal
        # nativamente. É o único float deste repositório que **escreve** saldo;
        # os demais são serialização de projeção.
        "quantity": qty_dec,
        "now": now
    }).first()

    new_balance = Decimal(str(result[0]))
    previous_balance = new_balance - qty_dec

    # Não existe saldo negativo: uma saída maior que o disponível é recusada, seja
    # ela venda, perda ou diferença apurada. Antes só a venda era barrada, o que
    # deixava a perda cavar saldo negativo por um caminho paralelo.
    if new_balance < Decimal("0.00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"INSUFFICIENT_STOCK: saldo insuficiente para '{product.name}'. "
                f"Disponível: {previous_balance}, solicitado: {abs(qty_dec)}."
            )
        )

    # 4. Create Immutable InventoryMovement (Source of Truth Ledger)
    movement = InventoryMovement(
        tenant_id=context.tenant_id,
        store_id=store_id,
        product_id=product_id,
        actor_id=actor_id,
        movement_type=movement_type,
        quantity=qty_dec,
        previous_balance=previous_balance,
        new_balance=new_balance,
        reason=reason,
        correlation_id=correlation_id
    )
    session.add(movement)

    # 5. Atomic Reliability Integration: AuditEvent + OutboxEvent in single transaction
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=store_id,
        actor_id=actor_id,
        action="inventory.adjust",
        target=f"PRODUCT-{product_id}",
        audit_payload={
            "product_id": str(product_id),
            "movement_type": movement_type.value,
            "quantity": str(qty_dec),
            "previous_balance": str(previous_balance),
            "new_balance": str(new_balance),
            "reason": reason
        },
        aggregate_type="product",
        aggregate_id=str(product_id),
        event_type="inventory.adjusted",
        outbox_payload={
            "tenant_id": str(context.tenant_id),
            "store_id": str(store_id),
            "product_id": str(product_id),
            "movement_type": movement_type.value,
            "quantity": str(qty_dec),
            "previous_balance": str(previous_balance),
            "new_balance": str(new_balance),
            "reason": reason
        },
        correlation_id=correlation_id
    )

    # Sem commit aqui. Este serviço registra um movimento; quem confirma a
    # transação é quem coordena a operação inteira — a rota, para o ajuste
    # manual, e `payment_service` para a baixa da venda, que percorre vários
    # itens. Enquanto o commit vivia aqui dentro, a falha no segundo item de uma
    # venda deixava atrás de si o primeiro item baixado e a venda já marcada
    # como paga, porque o commit do primeiro item levava junto tudo o que
    # estivesse pendente na sessão.
    session.flush()

    # O UPSERT acima é SQL cru: a instância que o ORM tenha em memória para esta
    # linha continua com o saldo anterior até ser relida.
    balance = session.exec(
        select(InventoryBalance).where(
            InventoryBalance.tenant_id == context.tenant_id,
            InventoryBalance.store_id == store_id,
            InventoryBalance.product_id == product_id
        )
    ).one()
    session.refresh(balance)

    return movement, balance, True

def get_balance(session: Session, context: TenantContext, store_id: uuid.UUID, product_id: uuid.UUID) -> InventoryBalance:
    query = select(InventoryBalance).where(
        InventoryBalance.store_id == store_id,
        InventoryBalance.product_id == product_id
    )
    query = scope_tenant_query(query, InventoryBalance, context)
    balance = session.exec(query).first()
    if not balance:
        return InventoryBalance(
            tenant_id=context.tenant_id,
            store_id=store_id,
            product_id=product_id,
            quantity=Decimal("0.00")
        )
    return balance

def list_movements(
    session: Session,
    context: TenantContext,
    store_id: Optional[uuid.UUID] = None,
    product_id: Optional[uuid.UUID] = None
) -> List[InventoryMovement]:
    query = select(InventoryMovement)
    query = scope_tenant_query(query, InventoryMovement, context)
    if store_id:
        query = query.where(InventoryMovement.store_id == store_id)
    if product_id:
        query = query.where(InventoryMovement.product_id == product_id)
    query = query.order_by(InventoryMovement.created_at.desc())
    return session.exec(query).all()


def set_minimum_stock(
    session: Session,
    context: TenantContext,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    minimum_stock: Union[float, Decimal],
) -> InventoryBalance:
    if context.store_id and store_id != context.store_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Configuração fora da unidade ativa.")
    product_query = scope_tenant_query(select(Product).where(Product.id == product_id), Product, context)
    product = session.exec(product_query).first()
    if not product or not product.tracks_inventory:
        raise HTTPException(status_code=404, detail="Produto com controle de estoque não encontrado.")
    minimum = Decimal(str(minimum_stock))
    balance = session.exec(scope_tenant_query(select(InventoryBalance).where(
        InventoryBalance.store_id == store_id,
        InventoryBalance.product_id == product_id,
    ), InventoryBalance, context)).first()
    if not balance:
        balance = InventoryBalance(
            tenant_id=context.tenant_id, store_id=store_id, product_id=product_id,
            quantity=Decimal("0"), minimum_stock=minimum,
        )
        session.add(balance)
    else:
        balance.minimum_stock = minimum
        balance.updated_at = datetime.utcnow()
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=store_id,
        actor_id=resolve_actor(context),
        action="inventory.minimum_stock.updated", target=f"PRODUCT-{product_id}",
        audit_payload={"product_id": str(product_id), "minimum_stock": str(minimum)},
        aggregate_type="product", aggregate_id=str(product_id),
        event_type="inventory.minimum_stock.updated",
        outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(store_id), "product_id": str(product_id), "minimum_stock": str(minimum)},
    )
    session.commit(); session.refresh(balance)
    return balance
