import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select
from app.core.database import get_session
from app.core.context import TenantContext, get_tenant_context
from app.models.fiscal import FiscalDocument, FiscalDocumentTypeEnum
from app.services import fiscal_service, reliability_service

router = APIRouter()

class FiscalIssueDTO(BaseModel):
    sale_id: uuid.UUID
    actor_id: uuid.UUID
    document_type: FiscalDocumentTypeEnum = FiscalDocumentTypeEnum.NFCE
    simulate_status: Optional[str] = None  # None (AUTHORIZED), 'REJECTED', 'CONTINGENCY'

class FiscalCancelDTO(BaseModel):
    actor_id: uuid.UUID
    reason: str

@router.post("/documents/issue")
def issue_fiscal_document_endpoint(
    data: FiscalIssueDTO,
    context: TenantContext = Depends(get_tenant_context),
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID"),
    session: Session = Depends(get_session)
):
    if x_idempotency_key:
        is_cached, status_code, body = reliability_service.check_idempotency(
            session=session,
            tenant_id=context.tenant_id,
            actor_id=data.actor_id,
            operation=f"POST /api/v1/fiscal/documents/issue",
            idempotency_key=x_idempotency_key,
            request_payload=data.dict()
        )
        if is_cached and status_code and body:
            return body

    doc, sale, already_processed = fiscal_service.issue_fiscal_document(
        session=session,
        context=context,
        sale_id=data.sale_id,
        actor_id=data.actor_id,
        document_type=data.document_type,
        simulate_status=data.simulate_status,
        correlation_id=x_correlation_id
    )

    response_data = {
        "fiscal_document": doc.dict(),
        "sale_status": sale.status.value,
        "already_processed": already_processed
    }

    if x_idempotency_key:
        reliability_service.save_idempotency_record(
            session=session,
            tenant_id=context.tenant_id,
            actor_id=data.actor_id,
            operation=f"POST /api/v1/fiscal/documents/issue",
            idempotency_key=x_idempotency_key,
            request_payload=data.dict(),
            response_status=200,
            response_body=response_data
        )

    session.commit()
    return response_data

@router.post("/documents/{fiscal_document_id}/cancel")
def cancel_fiscal_document_endpoint(
    fiscal_document_id: uuid.UUID,
    data: FiscalCancelDTO,
    context: TenantContext = Depends(get_tenant_context),
    x_correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID"),
    session: Session = Depends(get_session)
):
    return fiscal_service.cancel_fiscal_document(
        session=session,
        context=context,
        fiscal_document_id=fiscal_document_id,
        actor_id=data.actor_id,
        reason=data.reason,
        correlation_id=x_correlation_id
    )

@router.get("/documents/{fiscal_document_id}", response_model=FiscalDocument)
def get_fiscal_document_endpoint(
    fiscal_document_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    query = select(FiscalDocument).where(
        FiscalDocument.id == fiscal_document_id,
        FiscalDocument.tenant_id == context.tenant_id
    )
    doc = session.exec(query).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fiscal document not found.")
    return doc
