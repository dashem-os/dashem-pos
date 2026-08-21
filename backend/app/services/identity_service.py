import uuid
from sqlmodel import Session, select
from fastapi import HTTPException, status
from app.models.identity import Tenant, Store, User, Membership, RoleEnum

def create_tenant(session: Session, name: str, slug: str) -> Tenant:
    existing = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tenant with slug '{slug}' already exists."
        )
    tenant = Tenant(name=name, slug=slug)
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant

def create_store(session: Session, tenant_id: uuid.UUID, name: str, code: str) -> Store:
    tenant = session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found."
        )
    store = Store(tenant_id=tenant_id, name=name, code=code)
    session.add(store)
    session.commit()
    session.refresh(store)
    return store

def create_user(session: Session, email: str, full_name: str, password_hash: str) -> User:
    existing = session.exec(select(User).where(User.email == email)).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User with email '{email}' already exists."
        )
    user = User(email=email, full_name=full_name, password_hash=password_hash)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user

def create_membership(
    session: Session,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    role: RoleEnum
) -> Membership:
    # Invariant Check: Store MUST belong to the specified Tenant
    store = session.get(Store, store_id)
    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Store not found."
        )
    if store.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Store '{store_id}' does not belong to Tenant '{tenant_id}'."
        )
    
    # Check UNIQUE constraint
    existing = session.exec(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.tenant_id == tenant_id,
            Membership.store_id == store_id
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Membership already exists for this User, Tenant, and Store."
        )

    membership = Membership(
        user_id=user_id,
        tenant_id=tenant_id,
        store_id=store_id,
        role=role
    )
    session.add(membership)
    session.commit()
    session.refresh(membership)
    return membership
