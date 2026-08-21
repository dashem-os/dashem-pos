import uuid
from decimal import Decimal
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from app.core.context import TenantContext, scope_tenant_query
from app.models.identity import Store
from app.models.catalog import Product, ProductPrice
from app.models.sale import Customer, Sale, SaleItem, SaleStatusEnum, DiscountTypeEnum
from app.models.payment import Payment, PaymentStatusEnum
from app.services import reliability_service

def check_no_confirmed_payments(session: Session, sale_id: uuid.UUID) -> None:
    confirmed = session.exec(
        select(Payment).where(
            Payment.sale_id == sale_id,
            Payment.status == PaymentStatusEnum.CONFIRMED
        )
    ).all()
    if confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CANNOT_MODIFY_SALE_WITH_CONFIRMED_PAYMENTS: Cannot modify items, discount or cancel a sale with confirmed payments."
        )


def create_customer(
    session: Session,
    context: TenantContext,
    name: str,
    cpf_cnpj: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None
) -> Customer:
    if cpf_cnpj:
        existing_query = select(Customer).where(Customer.cpf_cnpj == cpf_cnpj)
        existing_query = scope_tenant_query(existing_query, Customer, context)
        if session.exec(existing_query).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Customer with CPF/CNPJ '{cpf_cnpj}' already exists for this tenant."
            )
            
    customer = Customer(
        tenant_id=context.tenant_id,
        name=name,
        cpf_cnpj=cpf_cnpj,
        phone=phone,
        email=email
    )
    session.add(customer)
    session.commit()
    session.refresh(customer)
    return customer

def list_customers(session: Session, context: TenantContext) -> List[Customer]:
    query = select(Customer)
    query = scope_tenant_query(query, Customer, context)
    return session.exec(query).all()

def create_sale(
    session: Session,
    context: TenantContext,
    store_id: uuid.UUID,
    customer_id: Optional[uuid.UUID] = None,
    seller_id: Optional[uuid.UUID] = None,
    notes: Optional[str] = None,
    actor_id: Optional[uuid.UUID] = None
) -> Sale:
    # Verify Store belongs to Tenant
    store = session.get(Store, store_id)
    if not store or store.tenant_id != context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Store '{store_id}' does not belong to Tenant '{context.tenant_id}'."
        )

    # If customer provided, verify belongs to Tenant
    if customer_id:
        cust_query = select(Customer).where(Customer.id == customer_id)
        cust_query = scope_tenant_query(cust_query, Customer, context)
        if not session.exec(cust_query).first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer '{customer_id}' not found for this tenant."
            )

    sale = Sale(
        tenant_id=context.tenant_id,
        store_id=store_id,
        customer_id=customer_id,
        seller_id=seller_id,
        status=SaleStatusEnum.DRAFT,
        notes=notes
    )
    session.add(sale)
    session.flush()

    # Emit Lifecycle Event: sale.created
    if actor_id:
        reliability_service.write_audit_and_outbox(
            session=session,
            tenant_id=context.tenant_id,
            store_id=store_id,
            actor_id=actor_id,
            action="sale.create",
            target=f"SALE-{sale.id}",
            audit_payload={"sale_id": str(sale.id), "status": sale.status.value},
            aggregate_type="sale",
            aggregate_id=str(sale.id),
            event_type="sale.created",
            outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(store_id), "sale_id": str(sale.id)}
        )

    session.commit()
    session.refresh(sale)
    return sale

def add_sale_item(
    session: Session,
    context: TenantContext,
    sale_id: uuid.UUID,
    product_id: uuid.UUID,
    quantity: Decimal,
    requested_discount: Decimal = Decimal("0.00")
) -> SaleItem:
    # Verify Sale belongs to tenant and is in DRAFT/CHECKOUT
    sale_query = select(Sale).where(Sale.id == sale_id)
    sale_query = scope_tenant_query(sale_query, Sale, context)
    sale = session.exec(sale_query).first()
    if not sale:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found for this tenant.")
    
    if sale.status not in (SaleStatusEnum.DRAFT, SaleStatusEnum.CHECKOUT, SaleStatusEnum.AWAITING_PAYMENT):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot add items to sale in status '{sale.status}'."
        )
    
    check_no_confirmed_payments(session, sale_id)
    if sale.status == SaleStatusEnum.AWAITING_PAYMENT:
        sale.status = SaleStatusEnum.DRAFT
        session.add(sale)

    # Verify Product belongs to tenant
    prod_query = select(Product).where(Product.id == product_id)
    prod_query = scope_tenant_query(prod_query, Product, context)
    product = session.exec(prod_query).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product '{product_id}' does not belong to Tenant '{context.tenant_id}'."
        )

    # SERVER-SIDE PRICE RESOLUTION: Lookup price for store or tenant
    price_query = select(ProductPrice).where(
        ProductPrice.product_id == product_id,
        ProductPrice.store_id == sale.store_id
    )
    price_query = scope_tenant_query(price_query, ProductPrice, context)
    price_record = session.exec(price_query).first()

    if not price_record:
        # Fallback to tenant-wide price (where store_id is NULL)
        fallback_query = select(ProductPrice).where(
            ProductPrice.product_id == product_id,
            ProductPrice.store_id == None
        )
        fallback_query = scope_tenant_query(fallback_query, ProductPrice, context)
        price_record = session.exec(fallback_query).first()

    if not price_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No price found for product '{product.name}' in store '{sale.store_id}'."
        )

    unit_price = Decimal(str(price_record.sale_price))
    qty_dec = Decimal(str(quantity))
    disc_dec = Decimal(str(requested_discount))

    gross_total = unit_price * qty_dec
    net_total = gross_total - disc_dec
    if net_total < Decimal("0.00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Item discount cannot result in negative net total."
        )

    # Historical & Operational Snapshot Assignment
    item = SaleItem(
        tenant_id=context.tenant_id,
        sale_id=sale_id,
        product_id=product_id,
        product_name=product.name,
        sku=product.sku,
        item_type_snapshot=product.item_type.value,
        tracks_inventory_snapshot=product.tracks_inventory,
        requires_fulfillment_snapshot=product.requires_fulfillment,
        unit_price=unit_price,
        quantity=qty_dec,
        discount_amount=disc_dec,
        gross_total=gross_total,
        net_total=net_total
    )
    session.add(item)
    session.flush()

    # Recalculate Sale Totals
    recalculate_sale_totals(session, sale)
    session.commit()
    session.refresh(item)
    return item

def recalculate_sale_totals(session: Session, sale: Sale) -> None:
    items_query = select(SaleItem).where(SaleItem.sale_id == sale.id)
    items = session.exec(items_query).all()
    
    gross = sum((item.gross_total for item in items), Decimal("0.00"))
    item_discounts = sum((item.discount_amount for item in items), Decimal("0.00"))
    
    sale.gross_total = gross
    sale.discount_total = item_discounts + sale.approved_discount
    sale.net_total = max(Decimal("0.00"), gross - sale.discount_total)
    sale.updated_at = datetime.utcnow()
    session.add(sale)

def update_sale_item(
    session: Session,
    context: TenantContext,
    sale_id: uuid.UUID,
    item_id: uuid.UUID,
    quantity: Decimal,
    requested_discount: Optional[Decimal] = None
) -> SaleItem:
    sale = get_sale(session, context, sale_id)
    if sale.status not in (SaleStatusEnum.DRAFT, SaleStatusEnum.CHECKOUT, SaleStatusEnum.AWAITING_PAYMENT):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot edit items in status '{sale.status}'.")
    check_no_confirmed_payments(session, sale_id)
    
    if sale.status == SaleStatusEnum.AWAITING_PAYMENT:
        sale.status = SaleStatusEnum.DRAFT
        session.add(sale)

    item_query = select(SaleItem).where(SaleItem.id == item_id, SaleItem.sale_id == sale_id)
    item = session.exec(item_query).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale item not found.")
        
    if quantity <= Decimal("0.00"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quantity must be greater than 0.")
        
    item.quantity = quantity
    item.gross_total = item.unit_price * quantity
    if requested_discount is not None:
        if requested_discount < Decimal("0.00"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Discount cannot be negative.")
        item.discount_amount = requested_discount
    
    item.net_total = item.gross_total - item.discount_amount
    if item.net_total < Decimal("0.00"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item discount cannot exceed gross total.")
        
    session.add(item)
    recalculate_sale_totals(session, sale)
    session.commit()
    session.refresh(item)
    return item

def delete_sale_item(
    session: Session,
    context: TenantContext,
    sale_id: uuid.UUID,
    item_id: uuid.UUID
) -> Sale:
    sale_query = select(Sale).where(Sale.id == sale_id)
    sale_query = scope_tenant_query(sale_query, Sale, context)
    sale = session.exec(sale_query).first()
    if not sale:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found for this tenant.")

    if sale.status not in (SaleStatusEnum.DRAFT, SaleStatusEnum.CHECKOUT, SaleStatusEnum.AWAITING_PAYMENT):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot delete items in status '{sale.status}'.")
    check_no_confirmed_payments(session, sale_id)

    if sale.status == SaleStatusEnum.AWAITING_PAYMENT:
        sale.status = SaleStatusEnum.DRAFT

    item_query = select(SaleItem).where(SaleItem.id == item_id, SaleItem.sale_id == sale_id)
    item = session.exec(item_query).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale item not found.")
        
    session.delete(item)
    session.commit()

    # Re-query sale and recalculate cleanly
    refreshed_sale = get_sale(session, context, sale_id)
    recalculate_sale_totals(session, refreshed_sale)
    session.commit()
    session.refresh(refreshed_sale)
    return refreshed_sale


def apply_sale_discount(
    session: Session,
    context: TenantContext,
    sale_id: uuid.UUID,
    discount_type: DiscountTypeEnum,
    value: Decimal
) -> Sale:
    sale = get_sale(session, context, sale_id)
    if sale.status not in (SaleStatusEnum.DRAFT, SaleStatusEnum.CHECKOUT, SaleStatusEnum.AWAITING_PAYMENT):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot apply discount in status '{sale.status}'.")
    check_no_confirmed_payments(session, sale_id)
    
    if value < Decimal("0.00"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Discount value cannot be negative.")
        
    items_query = select(SaleItem).where(SaleItem.sale_id == sale_id)
    items = session.exec(items_query).all()
    gross_total = sum((item.gross_total for item in items), Decimal("0.00"))
    item_discounts = sum((item.discount_amount for item in items), Decimal("0.00"))
    
    if discount_type == DiscountTypeEnum.PERCENTAGE:
        if value > Decimal("100.00"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Percentage discount cannot exceed 100%.")
        additional_discount = (gross_total * value) / Decimal("100.00")
    else:  # FIXED
        if value > gross_total:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fixed discount cannot exceed sale gross total.")
        additional_discount = value
        
    total_discount = item_discounts + additional_discount
    if total_discount > gross_total:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Total discount cannot exceed sale gross total.")
        
    sale.discount_type = discount_type
    sale.requested_discount = value
    sale.approved_discount = additional_discount
    sale.gross_total = gross_total
    sale.discount_total = total_discount
    sale.net_total = max(Decimal("0.00"), gross_total - total_discount)
    sale.updated_at = datetime.utcnow()
    
    session.add(sale)
    session.commit()
    session.refresh(sale)
    return sale

def cancel_sale(
    session: Session,
    context: TenantContext,
    sale_id: uuid.UUID,
    actor_id: Optional[uuid.UUID] = None,
    reason: Optional[str] = None
) -> Sale:
    sale = get_sale(session, context, sale_id)
    if sale.status in (SaleStatusEnum.COMPLETED, SaleStatusEnum.CANCELED, SaleStatusEnum.PAID):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot cancel sale in status '{sale.status}'.")
    check_no_confirmed_payments(session, sale_id)
    
    # Cancel any pending payments
    pending_payments = session.exec(
        select(Payment).where(Payment.sale_id == sale_id, Payment.status == PaymentStatusEnum.PENDING)
    ).all()
    for p in pending_payments:
        p.status = PaymentStatusEnum.FAILED
        session.add(p)
        
    sale.status = SaleStatusEnum.CANCELED
    sale.notes = f"{sale.notes or ''} [Cancelada: {reason or 'Sem motivo especificado'}]".strip()
    sale.updated_at = datetime.utcnow()
    session.add(sale)
    
    if actor_id:
        reliability_service.write_audit_and_outbox(
            session=session,
            tenant_id=context.tenant_id,
            store_id=sale.store_id,
            actor_id=actor_id,
            action="sale.cancel",
            target=f"SALE-{sale.id}",
            audit_payload={"sale_id": str(sale.id), "reason": reason},
            aggregate_type="sale",
            aggregate_id=str(sale.id),
            event_type="sale.canceled",
            outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(sale.store_id), "sale_id": str(sale.id)}
        )
        
    session.commit()
    session.refresh(sale)
    return sale

def list_sales(
    session: Session,
    context: TenantContext,
    store_id: Optional[uuid.UUID] = None,
    status_filter: Optional[SaleStatusEnum] = None
) -> List[Sale]:
    query = select(Sale).options(selectinload(Sale.items)).where(Sale.tenant_id == context.tenant_id)
    if store_id:
        query = query.where(Sale.store_id == store_id)
    if status_filter:
        query = query.where(Sale.status == status_filter)
    return session.exec(query.order_by(Sale.created_at.desc())).all()

def checkout_sale(
    session: Session,
    context: TenantContext,
    sale_id: uuid.UUID,
    actor_id: uuid.UUID,
    requested_discount: Decimal = Decimal("0.00"),
    discount_type: Optional[DiscountTypeEnum] = None,
    correlation_id: Optional[str] = None
) -> Sale:
    # PESSIMISTIC LOCKING: Lock the Sale record to prevent concurrent checkout race conditions
    sale_query = select(Sale).where(Sale.id == sale_id).with_for_update()
    sale_query = scope_tenant_query(sale_query, Sale, context)
    sale = session.exec(sale_query).first()
    if not sale:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found for this tenant.")

    # State Machine Verification: Can only checkout from DRAFT or CHECKOUT
    if sale.status not in (SaleStatusEnum.DRAFT, SaleStatusEnum.CHECKOUT):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid state transition from '{sale.status}' to CHECKOUT/AWAITING_PAYMENT."
        )


    items_query = select(SaleItem).where(SaleItem.sale_id == sale_id)
    items = session.exec(items_query).all()
    if not items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot checkout an empty sale.")

    req_disc_dec = Decimal(str(requested_discount))
    gross_total = sum((item.gross_total for item in items), Decimal("0.00"))
    item_discounts = sum((item.discount_amount for item in items), Decimal("0.00"))

    # Compute overall sale discount
    if discount_type == DiscountTypeEnum.PERCENTAGE:
        additional_discount = (gross_total * req_disc_dec) / Decimal("100.00")
    else:
        additional_discount = req_disc_dec if req_disc_dec > Decimal("0.00") else sale.approved_discount

    total_discount = item_discounts + additional_discount
    net_total = gross_total - total_discount

    if net_total < Decimal("0.00"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sale total discount cannot produce a negative net total.")

    sale.discount_type = discount_type or sale.discount_type
    sale.requested_discount = req_disc_dec if req_disc_dec > Decimal("0.00") else sale.requested_discount
    sale.approved_discount = additional_discount
    sale.gross_total = gross_total
    sale.discount_total = total_discount
    sale.net_total = net_total
    sale.status = SaleStatusEnum.AWAITING_PAYMENT
    sale.updated_at = datetime.utcnow()
    session.add(sale)

    # Atomic Reliability Integration: AuditEvent("sale.checkout") + OutboxEvent("sale.awaiting_payment")
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=sale.store_id,
        actor_id=actor_id,
        action="sale.checkout",
        target=f"SALE-{sale.id}",
        audit_payload={
            "sale_id": str(sale.id),
            "status": sale.status.value,
            "gross_total": str(sale.gross_total),
            "discount_total": str(sale.discount_total),
            "net_total": str(sale.net_total),
            "items_count": len(items)
        },
        aggregate_type="sale",
        aggregate_id=str(sale.id),
        event_type="sale.awaiting_payment",  # Correct Lifecycle Event
        outbox_payload={
            "tenant_id": str(context.tenant_id),
            "store_id": str(sale.store_id),
            "sale_id": str(sale.id),
            "status": sale.status.value,
            "net_total": str(sale.net_total)
        },
        correlation_id=correlation_id
    )

    session.commit()
    session.refresh(sale)
    return sale

def get_sale(session: Session, context: TenantContext, sale_id: uuid.UUID) -> Sale:
    query = select(Sale).options(selectinload(Sale.items)).where(Sale.id == sale_id)
    query = scope_tenant_query(query, Sale, context)
    sale = session.exec(query).first()
    if not sale:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found for this tenant.")
    return sale

