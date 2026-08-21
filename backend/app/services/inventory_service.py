import uuid
from decimal import Decimal
from datetime import datetime
from typing import List, Optional, Tuple, Union
from sqlmodel import Session, select, text
from fastapi import HTTPException, status
from app.core.context import TenantContext, scope_tenant_query
from app.models.catalog import Product, InventoryMovement, InventoryBalance, MovementTypeEnum
from app.services import reliability_service

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
    qty_dec = Decimal(str(quantity))

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
        "quantity": float(qty_dec),
        "now": now
    }).first()

    new_balance = Decimal(str(result[0]))
    previous_balance = new_balance - qty_dec

    # STRICT STOCK POLICY: Reject stock decrement if balance becomes negative
    if movement_type == MovementTypeEnum.SALE and new_balance < Decimal("0.00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"INSUFFICIENT_STOCK: Insufficient stock for product '{product.name}'. Available: {previous_balance}, Requested: {abs(qty_dec)}."
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

    session.commit()
    session.refresh(movement)

    # Read updated balance object AFTER commit (zero ORM insert collision)
    balance = session.exec(
        select(InventoryBalance).where(
            InventoryBalance.tenant_id == context.tenant_id,
            InventoryBalance.store_id == store_id,
            InventoryBalance.product_id == product_id
        )
    ).one()

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
