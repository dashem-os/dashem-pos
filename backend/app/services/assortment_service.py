import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional, List, Set
from fastapi import HTTPException, status as http_status
from sqlalchemy import func, or_, and_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.assortment import (
    Assortment, AssortmentScope, AssortmentProduct, AssortmentStatusEnum, SalesContextEnum,
)
from app.models.catalog import Product, Category, ProductPrice
from app.models.identity import Store
from app.models.channel import SalesChannel
from app.services import reliability_service


def resolve_effective_product_ids(
    session: Session,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    sales_context: SalesContextEnum,
    channel_id: Optional[uuid.UUID] = None,
    activity: Optional[str] = None,
) -> Set[uuid.UUID]:
    """Resolve the set of sellable product IDs authorized for the given context.

    Canonical resolution:
    Master Product -> Assortment -> Business Activity -> Store -> Channel -> Sales Context.
    Invariant: No silent fallback to global catalog. If no assortment or no products are linked,
    an empty set is returned.

    When an activity is given, only assortments curated for that activity resolve,
    plus the ones left activity-agnostic. That is what stops a food service
    operation from surfacing a hardware or perfumery catalogue on its own POS.
    """
    query = (
        select(AssortmentProduct.product_id)
        .join(Assortment, Assortment.id == AssortmentProduct.assortment_id)
        .join(AssortmentScope, AssortmentScope.assortment_id == Assortment.id)
        .where(
            Assortment.tenant_id == tenant_id,
            Assortment.status == AssortmentStatusEnum.ACTIVE,
            AssortmentProduct.tenant_id == tenant_id,
            AssortmentScope.tenant_id == tenant_id,
            AssortmentScope.store_id == store_id,
            AssortmentScope.sales_context == sales_context,
        )
    )
    if activity:
        query = query.where(
            or_(Assortment.business_activity.is_(None), Assortment.business_activity == activity)
        )
    if channel_id:
        query = query.where(or_(AssortmentScope.channel_id == channel_id, AssortmentScope.channel_id.is_(None)))
    else:
        query = query.where(AssortmentScope.channel_id.is_(None))

    rows = session.exec(query).all()
    return set(rows)


def list_assortments(
    session: Session,
    context: TenantContext,
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    status_filter: Optional[AssortmentStatusEnum] = None,
    store_id: Optional[uuid.UUID] = None,
    sales_context: Optional[SalesContextEnum] = None,
) -> dict[str, Any]:
    query = select(Assortment).where(Assortment.tenant_id == context.tenant_id)
    if status_filter:
        query = query.where(Assortment.status == status_filter)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Assortment.name.ilike(term), Assortment.code.ilike(term)))
    if store_id or sales_context:
        scope_sub = select(AssortmentScope.assortment_id).where(AssortmentScope.tenant_id == context.tenant_id)
        if store_id:
            scope_sub = scope_sub.where(AssortmentScope.store_id == store_id)
        if sales_context:
            scope_sub = scope_sub.where(AssortmentScope.sales_context == sales_context)
        query = query.where(Assortment.id.in_(scope_sub))

    count_query = select(func.count()).select_from(query.subquery())
    total = session.exec(count_query).one()

    query = query.order_by(Assortment.name).offset((page - 1) * page_size).limit(page_size)
    assortments = list(session.exec(query).all())

    items = []
    for ass in assortments:
        scopes = list(session.exec(
            select(AssortmentScope).where(
                AssortmentScope.tenant_id == context.tenant_id,
                AssortmentScope.assortment_id == ass.id,
            )
        ).all())
        prod_count = session.exec(
            select(func.count(AssortmentProduct.id)).where(
                AssortmentProduct.tenant_id == context.tenant_id,
                AssortmentProduct.assortment_id == ass.id,
            )
        ).one()
        items.append({
            "id": ass.id,
            "tenant_id": ass.tenant_id,
            "code": ass.code,
            "name": ass.name,
            "description": ass.description,
            "business_activity": ass.business_activity,
            "status": ass.status,
            "version": ass.version,
            "created_at": ass.created_at,
            "updated_at": ass.updated_at,
            "product_count": prod_count,
            "scopes": [
                {
                    "id": s.id,
                    "store_id": s.store_id,
                    "channel_id": s.channel_id,
                    "sales_context": s.sales_context,
                    "created_at": s.created_at,
                }
                for s in scopes
            ],
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_assortment(session: Session, context: TenantContext, assortment_id: uuid.UUID) -> dict[str, Any]:
    ass = session.exec(
        select(Assortment).where(
            Assortment.tenant_id == context.tenant_id,
            Assortment.id == assortment_id,
        )
    ).first()
    if not ass:
        raise HTTPException(status_code=404, detail="Sortimento não encontrado.")

    scopes = list(session.exec(
        select(AssortmentScope).where(
            AssortmentScope.tenant_id == context.tenant_id,
            AssortmentScope.assortment_id == ass.id,
        )
    ).all())
    prod_count = session.exec(
        select(func.count(AssortmentProduct.id)).where(
            AssortmentProduct.tenant_id == context.tenant_id,
            AssortmentProduct.assortment_id == ass.id,
        )
    ).one()

    return {
        "id": ass.id,
        "tenant_id": ass.tenant_id,
        "code": ass.code,
        "name": ass.name,
        "description": ass.description,
        "business_activity": ass.business_activity,
        "status": ass.status,
        "version": ass.version,
        "created_at": ass.created_at,
        "updated_at": ass.updated_at,
        "product_count": prod_count,
        "scopes": [
            {
                "id": s.id,
                "store_id": s.store_id,
                "channel_id": s.channel_id,
                "sales_context": s.sales_context,
                "created_at": s.created_at,
            }
            for s in scopes
        ],
    }


def create_assortment(
    session: Session,
    context: TenantContext,
    *,
    code: str,
    name: str,
    description: Optional[str] = None,
    business_activity: Optional[str] = None,
    status: AssortmentStatusEnum = AssortmentStatusEnum.ACTIVE,
    scopes: Optional[List[dict[str, Any]]] = None,
    product_ids: Optional[List[uuid.UUID]] = None,
    idempotency_key: Optional[str] = None,
    actor_id: Optional[uuid.UUID] = None,
) -> dict[str, Any]:
    actor = resolve_actor(context, actor_id)

    payload = {
        "code": code.strip(),
        "name": name.strip(),
        "description": description.strip() if description else None,
        "business_activity": business_activity,
        "status": status.value,
        "scopes": scopes or [],
        "product_ids": [str(pid) for pid in (product_ids or [])],
    }

    if idempotency_key:
        hit, _, body = reliability_service.check_idempotency(
            session, context.tenant_id, actor, "assortment.create", idempotency_key, payload
        )
        if hit and body:
            return body

    existing = session.exec(
        select(Assortment).where(
            Assortment.tenant_id == context.tenant_id,
            Assortment.code == code.strip(),
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Sortimento com código '{code.strip()}' já existe no tenant.",
        )

    assortment = Assortment(
        tenant_id=context.tenant_id,
        code=code.strip(),
        name=name.strip(),
        description=description.strip() if description else None,
        business_activity=business_activity,
        status=status,
        version=1,
    )
    session.add(assortment)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        if idempotency_key:
            exists, _, body = reliability_service.check_idempotency(
                session, context.tenant_id, actor, "assortment.create", idempotency_key, payload
            )
            if exists and body is not None:
                return body
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Conflito ao criar sortimento: código ou chave de idempotência já utilizado.",
        ) from exc

    # Add Scopes
    if scopes:
        for sc in scopes:
            store_id = uuid.UUID(str(sc["store_id"]))
            store = session.get(Store, store_id)
            if not store or store.tenant_id != context.tenant_id:
                raise HTTPException(status_code=400, detail=f"Unidade '{store_id}' inválida.")
            channel_id = uuid.UUID(str(sc["channel_id"])) if sc.get("channel_id") else None
            if channel_id:
                channel = session.get(SalesChannel, channel_id)
                if not channel or channel.tenant_id != context.tenant_id:
                    raise HTTPException(status_code=400, detail=f"Canal '{channel_id}' inválido.")
            sales_context = SalesContextEnum(sc["sales_context"])
            scope_obj = AssortmentScope(
                tenant_id=context.tenant_id,
                assortment_id=assortment.id,
                store_id=store_id,
                channel_id=channel_id,
                sales_context=sales_context,
            )
            session.add(scope_obj)

    # Add Products
    if product_ids:
        seen_pids = set()
        for pid in product_ids:
            if pid in seen_pids:
                continue
            seen_pids.add(pid)
            prod = session.exec(
                select(Product).where(
                    Product.tenant_id == context.tenant_id,
                    Product.id == pid,
                )
            ).first()
            if not prod:
                raise HTTPException(status_code=400, detail=f"Produto '{pid}' não encontrado no catálogo.")
            link = AssortmentProduct(
                tenant_id=context.tenant_id,
                assortment_id=assortment.id,
                product_id=pid,
            )
            session.add(link)

    audit_payload = {
        "assortment_id": str(assortment.id),
        "code": assortment.code,
        "name": assortment.name,
        "version": assortment.version,
    }
    outbox_payload = {
        "assortment_id": str(assortment.id),
        "tenant_id": str(context.tenant_id),
        "version": assortment.version,
    }
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=context.store_id,
        actor_id=actor,
        action="assortment.created",
        target=f"assortment:{assortment.id}",
        audit_payload=audit_payload,
        aggregate_type="assortment",
        aggregate_id=str(assortment.id),
        event_type="assortment.created",
        outbox_payload=outbox_payload,
    )

    session.flush()

    result = get_assortment(session, context, assortment.id)
    if idempotency_key:
        reliability_service.save_idempotency_record(
            session, context.tenant_id, actor, "assortment.create", idempotency_key, payload, 201, result
        )

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if idempotency_key:
            exists, _, body = reliability_service.check_idempotency(
                session, context.tenant_id, actor, "assortment.create", idempotency_key, payload
            )
            if exists and body is not None:
                return body
        raise HTTPException(status_code=409, detail="Conflito de concorrência ou chave de idempotência duplicada.") from exc
    return result


def update_assortment(
    session: Session,
    context: TenantContext,
    assortment_id: uuid.UUID,
    *,
    expected_version: int,
    code: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    business_activity: Optional[str] = None,
    business_activity_set: bool = False,
    status: Optional[AssortmentStatusEnum] = None,
    scopes: Optional[List[dict[str, Any]]] = None,
    idempotency_key: Optional[str] = None,
    actor_id: Optional[uuid.UUID] = None,
) -> dict[str, Any]:
    actor = resolve_actor(context, actor_id)

    payload = {
        "assortment_id": str(assortment_id),
        "expected_version": expected_version,
        "code": code.strip() if code else None,
        "name": name.strip() if name else None,
        "description": description.strip() if description is not None else None,
        "business_activity": business_activity,
        "business_activity_set": business_activity_set,
        "status": status.value if status else None,
        "scopes": scopes,
    }

    if idempotency_key:
        hit, _, body = reliability_service.check_idempotency(
            session, context.tenant_id, actor, "assortment.update", idempotency_key, payload
        )
        if hit and body:
            return body

    assortment = session.exec(
        select(Assortment).where(
            Assortment.tenant_id == context.tenant_id,
            Assortment.id == assortment_id,
        ).with_for_update()
    ).first()
    if not assortment:
        raise HTTPException(status_code=404, detail="Sortimento não encontrado.")

    if assortment.version != expected_version:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Conflito de versão: o sortimento está na versão {assortment.version}, esperado {expected_version}.",
        )

    if code and code.strip() != assortment.code:
        conflict = session.exec(
            select(Assortment).where(
                Assortment.tenant_id == context.tenant_id,
                Assortment.code == code.strip(),
                Assortment.id != assortment_id,
            )
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail=f"Código '{code.strip()}' já em uso.")
        assortment.code = code.strip()

    if name:
        assortment.name = name.strip()
    if description is not None:
        assortment.description = description.strip() if description else None
    # An explicit flag is required because clearing the activity back to
    # "every activity" is a legitimate edit that sends None.
    if business_activity_set:
        assortment.business_activity = business_activity
    if status:
        assortment.status = status

    if scopes is not None:
        # Replace scopes
        existing_scopes = session.exec(
            select(AssortmentScope).where(
                AssortmentScope.tenant_id == context.tenant_id,
                AssortmentScope.assortment_id == assortment.id,
            )
        ).all()
        for es in existing_scopes:
            session.delete(es)

        for sc in scopes:
            store_id = uuid.UUID(str(sc["store_id"]))
            store = session.get(Store, store_id)
            if not store or store.tenant_id != context.tenant_id:
                raise HTTPException(status_code=400, detail=f"Unidade '{store_id}' inválida.")
            channel_id = uuid.UUID(str(sc["channel_id"])) if sc.get("channel_id") else None
            if channel_id:
                channel = session.get(SalesChannel, channel_id)
                if not channel or channel.tenant_id != context.tenant_id:
                    raise HTTPException(status_code=400, detail=f"Canal '{channel_id}' inválido.")
            sales_context = SalesContextEnum(sc["sales_context"])
            session.add(AssortmentScope(
                tenant_id=context.tenant_id,
                assortment_id=assortment.id,
                store_id=store_id,
                channel_id=channel_id,
                sales_context=sales_context,
            ))

    assortment.version += 1
    assortment.updated_at = datetime.utcnow()
    session.add(assortment)

    audit_payload = {
        "assortment_id": str(assortment.id),
        "code": assortment.code,
        "name": assortment.name,
        "version": assortment.version,
    }
    outbox_payload = {
        "assortment_id": str(assortment.id),
        "tenant_id": str(context.tenant_id),
        "version": assortment.version,
    }
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=context.store_id,
        actor_id=actor,
        action="assortment.updated",
        target=f"assortment:{assortment.id}",
        audit_payload=audit_payload,
        aggregate_type="assortment",
        aggregate_id=str(assortment.id),
        event_type="assortment.updated",
        outbox_payload=outbox_payload,
    )

    session.flush()

    result = get_assortment(session, context, assortment.id)
    if idempotency_key:
        reliability_service.save_idempotency_record(
            session, context.tenant_id, actor, "assortment.update", idempotency_key, payload, 200, result
        )

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if idempotency_key:
            exists, _, body = reliability_service.check_idempotency(
                session, context.tenant_id, actor, "assortment.update", idempotency_key, payload
            )
            if exists and body is not None:
                return body
        raise HTTPException(status_code=409, detail="Conflito de concorrência ou chave de idempotência duplicada.") from exc
    return result


def link_products(
    session: Session,
    context: TenantContext,
    assortment_id: uuid.UUID,
    product_ids: List[uuid.UUID],
    *,
    expected_version: int,
    idempotency_key: Optional[str] = None,
    actor_id: Optional[uuid.UUID] = None,
) -> dict[str, Any]:
    actor = resolve_actor(context, actor_id)

    payload = {
        "assortment_id": str(assortment_id),
        "expected_version": expected_version,
        "product_ids": [str(pid) for pid in sorted(product_ids)],
    }

    if idempotency_key:
        hit, _, body = reliability_service.check_idempotency(
            session, context.tenant_id, actor, "assortment.link_products", idempotency_key, payload
        )
        if hit and body:
            return body

    assortment = session.exec(
        select(Assortment).where(
            Assortment.tenant_id == context.tenant_id,
            Assortment.id == assortment_id,
        ).with_for_update()
    ).first()
    if not assortment:
        raise HTTPException(status_code=404, detail="Sortimento não encontrado.")

    if assortment.version != expected_version:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Conflito de versão: o sortimento está na versão {assortment.version}, esperado {expected_version}.",
        )

    existing_links = set(session.exec(
        select(AssortmentProduct.product_id).where(
            AssortmentProduct.tenant_id == context.tenant_id,
            AssortmentProduct.assortment_id == assortment.id,
        )
    ).all())

    for pid in product_ids:
        if pid in existing_links:
            continue
        prod = session.exec(
            select(Product).where(
                Product.tenant_id == context.tenant_id,
                Product.id == pid,
            )
        ).first()
        if not prod:
            raise HTTPException(status_code=400, detail=f"Produto '{pid}' não encontrado no catálogo.")
        session.add(AssortmentProduct(
            tenant_id=context.tenant_id,
            assortment_id=assortment.id,
            product_id=pid,
        ))

    assortment.version += 1
    assortment.updated_at = datetime.utcnow()
    session.add(assortment)

    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=context.store_id,
        actor_id=actor,
        action="assortment.products_linked",
        target=f"assortment:{assortment.id}",
        audit_payload={"linked_count": len(product_ids), "version": assortment.version},
        aggregate_type="assortment",
        aggregate_id=str(assortment.id),
        event_type="assortment.products_linked",
        outbox_payload={"assortment_id": str(assortment.id), "version": assortment.version},
    )

    session.flush()

    result = get_assortment(session, context, assortment.id)
    if idempotency_key:
        reliability_service.save_idempotency_record(
            session, context.tenant_id, actor, "assortment.link_products", idempotency_key, payload, 200, result
        )

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if idempotency_key:
            exists, _, body = reliability_service.check_idempotency(
                session, context.tenant_id, actor, "assortment.link_products", idempotency_key, payload
            )
            if exists and body is not None:
                return body
        raise HTTPException(status_code=409, detail="Conflito de concorrência ou chave de idempotência duplicada.") from exc
    return result


def unlink_products(
    session: Session,
    context: TenantContext,
    assortment_id: uuid.UUID,
    product_ids: List[uuid.UUID],
    *,
    expected_version: int,
    idempotency_key: Optional[str] = None,
    actor_id: Optional[uuid.UUID] = None,
) -> dict[str, Any]:
    actor = resolve_actor(context, actor_id)

    payload = {
        "assortment_id": str(assortment_id),
        "expected_version": expected_version,
        "product_ids": [str(pid) for pid in sorted(product_ids)],
    }

    if idempotency_key:
        hit, _, body = reliability_service.check_idempotency(
            session, context.tenant_id, actor, "assortment.unlink_products", idempotency_key, payload
        )
        if hit and body:
            return body

    assortment = session.exec(
        select(Assortment).where(
            Assortment.tenant_id == context.tenant_id,
            Assortment.id == assortment_id,
        ).with_for_update()
    ).first()
    if not assortment:
        raise HTTPException(status_code=404, detail="Sortimento não encontrado.")

    if assortment.version != expected_version:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Conflito de versão: o sortimento está na versão {assortment.version}, esperado {expected_version}.",
        )

    links_to_remove = list(session.exec(
        select(AssortmentProduct).where(
            AssortmentProduct.tenant_id == context.tenant_id,
            AssortmentProduct.assortment_id == assortment.id,
            AssortmentProduct.product_id.in_(product_ids),
        )
    ).all())

    for link in links_to_remove:
        session.delete(link)

    assortment.version += 1
    assortment.updated_at = datetime.utcnow()
    session.add(assortment)

    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=context.store_id,
        actor_id=actor,
        action="assortment.products_unlinked",
        target=f"assortment:{assortment.id}",
        audit_payload={"unlinked_count": len(links_to_remove), "version": assortment.version},
        aggregate_type="assortment",
        aggregate_id=str(assortment.id),
        event_type="assortment.products_unlinked",
        outbox_payload={"assortment_id": str(assortment.id), "version": assortment.version},
    )

    session.flush()

    result = get_assortment(session, context, assortment.id)
    if idempotency_key:
        reliability_service.save_idempotency_record(
            session, context.tenant_id, actor, "assortment.unlink_products", idempotency_key, payload, 200, result
        )

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if idempotency_key:
            exists, _, body = reliability_service.check_idempotency(
                session, context.tenant_id, actor, "assortment.unlink_products", idempotency_key, payload
            )
            if exists and body is not None:
                return body
        raise HTTPException(status_code=409, detail="Conflito de concorrência ou chave de idempotência duplicada.") from exc
    return result


def list_assortment_products(
    session: Session,
    context: TenantContext,
    assortment_id: uuid.UUID,
    page: int = 1,
    page_size: int = 50,
    search: Optional[str] = None,
) -> dict[str, Any]:
    assortment = session.exec(
        select(Assortment).where(
            Assortment.tenant_id == context.tenant_id,
            Assortment.id == assortment_id,
        )
    ).first()
    if not assortment:
        raise HTTPException(status_code=404, detail="Sortimento não encontrado.")

    query = (
        select(Product, AssortmentProduct.sort_order)
        .join(AssortmentProduct, AssortmentProduct.product_id == Product.id)
        .where(
            AssortmentProduct.tenant_id == context.tenant_id,
            AssortmentProduct.assortment_id == assortment_id,
            Product.tenant_id == context.tenant_id,
        )
    )
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Product.name.ilike(term), Product.sku.ilike(term), Product.barcode.ilike(term)))

    count_query = select(func.count()).select_from(query.subquery())
    total = session.exec(count_query).one()

    query = query.order_by(AssortmentProduct.sort_order, Product.name).offset((page - 1) * page_size).limit(page_size)
    rows = session.exec(query).all()

    items = []
    for prod, sort_order in rows:
        items.append({
            "id": prod.id,
            "name": prod.name,
            "sku": prod.sku,
            "barcode": prod.barcode,
            "unit": prod.unit,
            "category_id": prod.category_id,
            "is_active": prod.is_active,
            "available_for_sale": prod.available_for_sale,
            "sort_order": sort_order,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def delete_assortment(
    session: Session,
    context: TenantContext,
    assortment_id: uuid.UUID,
    *,
    expected_version: int,
    actor_id: Optional[uuid.UUID] = None,
) -> None:
    actor = resolve_actor(context, actor_id)
    assortment = session.exec(
        select(Assortment).where(
            Assortment.tenant_id == context.tenant_id,
            Assortment.id == assortment_id,
        ).with_for_update()
    ).first()
    if not assortment:
        raise HTTPException(status_code=404, detail="Sortimento não encontrado.")

    if assortment.version != expected_version:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Conflito de versão: o sortimento está na versão {assortment.version}, esperado {expected_version}.",
        )

    session.delete(assortment)
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=context.store_id,
        actor_id=actor,
        action="assortment.deleted",
        target=f"assortment:{assortment_id}",
        audit_payload={"assortment_id": str(assortment_id)},
        aggregate_type="assortment",
        aggregate_id=str(assortment_id),
        event_type="assortment.deleted",
        outbox_payload={"assortment_id": str(assortment_id)},
    )
    session.commit()
