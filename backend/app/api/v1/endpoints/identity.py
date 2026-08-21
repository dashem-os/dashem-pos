import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select
from app.core.database import get_session
from app.models.identity import Tenant, Store, User, Membership, RoleEnum
from app.services import identity_service, reliability_service

router = APIRouter()

# Schema DTOs
class TenantCreate(BaseModel):
    name: str
    slug: str

class StoreCreate(BaseModel):
    tenant_id: uuid.UUID
    name: str
    code: str

class UserCreate(BaseModel):
    email: str
    full_name: str
    password: str

class MembershipCreate(BaseModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    role: RoleEnum

class TestMutationRequest(BaseModel):
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    actor_id: uuid.UUID
    action_name: str
    payload_data: str

@router.post("/tenants", response_model=Tenant)
def create_tenant_endpoint(data: TenantCreate, session: Session = Depends(get_session)):
    return identity_service.create_tenant(session, name=data.name, slug=data.slug)

@router.get("/tenants", response_model=List[Tenant])
def list_tenants(session: Session = Depends(get_session)):
    return session.exec(select(Tenant)).all()

@router.post("/stores", response_model=Store)
def create_store_endpoint(data: StoreCreate, session: Session = Depends(get_session)):
    return identity_service.create_store(session, tenant_id=data.tenant_id, name=data.name, code=data.code)

@router.get("/stores", response_model=List[Store])
def list_stores(tenant_id: Optional[uuid.UUID] = None, session: Session = Depends(get_session)):
    query = select(Store)
    if tenant_id:
        query = query.where(Store.tenant_id == tenant_id)
    return session.exec(query).all()

@router.post("/users", response_model=User)
def create_user_endpoint(data: UserCreate, session: Session = Depends(get_session)):
    return identity_service.create_user(
        session, email=data.email, full_name=data.full_name, password_hash=f"hashed_{data.password}"
    )

@router.get("/users", response_model=List[User])
def list_users(session: Session = Depends(get_session)):
    return session.exec(select(User)).all()

@router.post("/memberships", response_model=Membership)
def create_membership_endpoint(data: MembershipCreate, session: Session = Depends(get_session)):
    return identity_service.create_membership(
        session,
        user_id=data.user_id,
        tenant_id=data.tenant_id,
        store_id=data.store_id,
        role=data.role
    )

@router.get("/memberships", response_model=List[Membership])
def list_memberships(
    user_id: Optional[uuid.UUID] = None,
    tenant_id: Optional[uuid.UUID] = None,
    session: Session = Depends(get_session)
):
    query = select(Membership)
    if user_id:
        query = query.where(Membership.user_id == user_id)
    if tenant_id:
        query = query.where(Membership.tenant_id == tenant_id)
    return session.exec(query).all()

@router.post("/test-atomic-mutation")
def test_atomic_mutation_endpoint(
    data: TestMutationRequest,
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID"),
    session: Session = Depends(get_session)
):
    # Check Idempotency if key header is provided
    if x_idempotency_key:
        is_cached, status_code, body = reliability_service.check_idempotency(
            session=session,
            tenant_id=data.tenant_id,
            actor_id=data.actor_id,
            operation="POST /test-atomic-mutation",
            idempotency_key=x_idempotency_key,
            request_payload=data.dict()
        )
        if is_cached and status_code and body:
            return body

    # Write Audit + Outbox in single transaction
    audit, outbox = reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=data.tenant_id,
        store_id=data.store_id,
        actor_id=data.actor_id,
        action=data.action_name,
        target=f"MUTATION-{uuid.uuid4().hex[:6]}",
        audit_payload={"data": data.payload_data},
        aggregate_type="test_aggregate",
        aggregate_id=str(uuid.uuid4()),
        event_type="test.mutated",
        outbox_payload={"data": data.payload_data},
        correlation_id=x_correlation_id
    )
    
    response_body = {
        "status": "success",
        "audit_id": str(audit.id),
        "outbox_id": str(outbox.id),
        "correlation_id": x_correlation_id
    }
    
    # Save Idempotency record if key header was provided
    if x_idempotency_key:
        response_body = reliability_service.save_idempotency_record(
            session=session,
            tenant_id=data.tenant_id,
            actor_id=data.actor_id,
            operation="POST /test-atomic-mutation",
            idempotency_key=x_idempotency_key,
            request_payload=data.dict(),
            response_status=200,
            response_body=response_body
        )

    session.commit()
    return response_body
