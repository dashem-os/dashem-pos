import uuid
import hashlib
import json
from datetime import datetime
from typing import Optional, Tuple, Dict, Any
from sqlmodel import Session, select
from fastapi import HTTPException, status
from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.sale import Sale, SaleStatusEnum
from app.models.fiscal import (
    FiscalDocument, FiscalEvent, FiscalStatusEnum, FiscalDocumentTypeEnum, FiscalEventTypeEnum
)
from app.providers.fiscal_provider import fiscal_gateway
from app.services import reliability_service

def compute_fiscal_request_hash(payload: Dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

def issue_fiscal_document(
    session: Session,
    context: TenantContext,
    sale_id: uuid.UUID,
    actor_id: uuid.UUID,
    document_type: FiscalDocumentTypeEnum = FiscalDocumentTypeEnum.NFCE,
    simulate_status: Optional[str] = None,
    correlation_id: Optional[str] = None
) -> Tuple[FiscalDocument, Sale, bool]:
    actor_id = resolve_actor(context, actor_id)
    # GATE 2: Pre-condition check — Lock Sale with FOR UPDATE
    sale_query = select(Sale).where(
        Sale.id == sale_id,
        Sale.tenant_id == context.tenant_id
    ).with_for_update()
    sale = session.exec(sale_query).first()
    if not sale:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found for this tenant.")

    if sale.status not in (SaleStatusEnum.PAID, SaleStatusEnum.COMPLETED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ONLY_PAID_SALES_CAN_ISSUE_FISCAL: Sale in status '{sale.status}' cannot issue fiscal document."
        )

    req_payload = {
        "sale_id": str(sale_id),
        "document_type": document_type.value,
        "simulate_status": simulate_status
    }
    req_hash = compute_fiscal_request_hash(req_payload)

    # GATE 5: Idempotency check for existing fiscal document
    existing_query = select(FiscalDocument).where(
        FiscalDocument.sale_id == sale_id,
        FiscalDocument.tenant_id == context.tenant_id
    ).with_for_update()
    doc = session.exec(existing_query).first()

    if doc and doc.status in (FiscalStatusEnum.AUTHORIZED, FiscalStatusEnum.NOT_REQUIRED):
        return doc, sale, True

    if not doc:
        doc = FiscalDocument(
            tenant_id=context.tenant_id,
            store_id=sale.store_id,
            sale_id=sale_id,
            document_type=document_type,
            status=FiscalStatusEnum.PENDING,
            request_hash=req_hash
        )
        session.add(doc)
        session.flush()
    else:
        doc.request_hash = req_hash
        doc.document_type = document_type

    doc.attempt_count += 1
    doc.last_attempt_at = datetime.utcnow()

    # Log Issuance Requested Event with Request Hash Snapshot
    event_req = FiscalEvent(
        tenant_id=context.tenant_id,
        store_id=sale.store_id,
        fiscal_document_id=doc.id,
        actor_id=actor_id,
        event_type=FiscalEventTypeEnum.ISSUANCE_REQUESTED,
        details=f"Solicitação de Emissão ({document_type.value}) [Hash: {req_hash[:8]}]"
    )
    session.add(event_req)

    # PATH A: NOT_REQUIRED FISCAL FLOW (document_type == NONE or simulate_status == 'NOT_REQUIRED')
    if document_type == FiscalDocumentTypeEnum.NONE or simulate_status == "NOT_REQUIRED":
        doc.status = FiscalStatusEnum.NOT_REQUIRED
        doc.issued_at = datetime.utcnow()

        # Transition Sale to COMPLETED
        sale.status = SaleStatusEnum.COMPLETED
        sale.updated_at = datetime.utcnow()
        session.add(sale)

        reliability_service.write_audit_and_outbox(
            session=session,
            tenant_id=context.tenant_id,
            store_id=sale.store_id,
            actor_id=actor_id,
            action="fiscal.not_required",
            target=f"FISCAL-{doc.id}",
            audit_payload={"fiscal_document_id": str(doc.id), "status": doc.status.value},
            aggregate_type="fiscal_document",
            aggregate_id=str(doc.id),
            event_type="fiscal.not_required",
            outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(sale.store_id), "sale_id": str(sale.id)},
            correlation_id=correlation_id
        )

        reliability_service.write_audit_and_outbox(
            session=session,
            tenant_id=context.tenant_id,
            store_id=sale.store_id,
            actor_id=actor_id,
            action="sale.complete",
            target=f"SALE-{sale.id}",
            audit_payload={"sale_id": str(sale.id), "status": sale.status.value},
            aggregate_type="sale",
            aggregate_id=str(sale.id),
            event_type="sale.completed",
            outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(sale.store_id), "sale_id": str(sale.id)},
            correlation_id=correlation_id
        )

        session.add(doc)
        session.commit()
        session.refresh(doc)
        session.refresh(sale)
        return doc, sale, False

    # PATH B: SEFAZ / PROVIDER EMISSION (NFCE, NFE, SAT)
    st, access_key, doc_num, xml_content, pdf_url, rej_code, rej_reason = fiscal_gateway.issue_document(
        tenant_id=context.tenant_id,
        store_id=sale.store_id,
        sale_id=sale_id,
        document_type=document_type,
        net_total=str(sale.net_total),
        simulate_status=simulate_status
    )

    doc.status = st
    doc.access_key = access_key
    doc.document_number = doc_num
    doc.xml_content = xml_content
    doc.pdf_url = pdf_url
    doc.rejection_code = rej_code
    doc.rejection_reason = rej_reason

    if st == FiscalStatusEnum.AUTHORIZED:
        doc.issued_at = datetime.utcnow()
        # GATE 10: Transition Sale to COMPLETED
        sale.status = SaleStatusEnum.COMPLETED
        sale.updated_at = datetime.utcnow()
        session.add(sale)

        event_auth = FiscalEvent(
            tenant_id=context.tenant_id,
            store_id=sale.store_id,
            fiscal_document_id=doc.id,
            actor_id=actor_id,
            event_type=FiscalEventTypeEnum.AUTHORIZED,
            details=f"Autorizado SEFAZ Chave: {access_key}"
        )
        session.add(event_auth)

        reliability_service.write_audit_and_outbox(
            session=session,
            tenant_id=context.tenant_id,
            store_id=sale.store_id,
            actor_id=actor_id,
            action="fiscal.issue",
            target=f"FISCAL-{doc.id}",
            audit_payload={"fiscal_document_id": str(doc.id), "access_key": access_key, "status": st.value},
            aggregate_type="fiscal_document",
            aggregate_id=str(doc.id),
            event_type="fiscal.authorized",
            outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(sale.store_id), "sale_id": str(sale.id), "access_key": access_key},
            correlation_id=correlation_id
        )

        reliability_service.write_audit_and_outbox(
            session=session,
            tenant_id=context.tenant_id,
            store_id=sale.store_id,
            actor_id=actor_id,
            action="sale.complete",
            target=f"SALE-{sale.id}",
            audit_payload={"sale_id": str(sale.id), "status": sale.status.value},
            aggregate_type="sale",
            aggregate_id=str(sale.id),
            event_type="sale.completed",
            outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(sale.store_id), "sale_id": str(sale.id)},
            correlation_id=correlation_id
        )

    elif st == FiscalStatusEnum.REJECTED:
        # GATE 8 & 9: Non-destructive rejection (Sale remains PAID, zero payment/stock rollback)
        event_rej = FiscalEvent(
            tenant_id=context.tenant_id,
            store_id=sale.store_id,
            fiscal_document_id=doc.id,
            actor_id=actor_id,
            event_type=FiscalEventTypeEnum.REJECTED,
            details=f"Rejeição SEFAZ [{rej_code}]: {rej_reason}"
        )
        session.add(event_rej)

        reliability_service.write_audit_and_outbox(
            session=session,
            tenant_id=context.tenant_id,
            store_id=sale.store_id,
            actor_id=actor_id,
            action="fiscal.reject",
            target=f"FISCAL-{doc.id}",
            audit_payload={"fiscal_document_id": str(doc.id), "rejection_code": rej_code, "status": st.value},
            aggregate_type="fiscal_document",
            aggregate_id=str(doc.id),
            event_type="fiscal.rejected",
            outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(sale.store_id), "sale_id": str(sale.id), "rejection_code": rej_code},
            correlation_id=correlation_id
        )

    elif st == FiscalStatusEnum.CONTINGENCY:
        event_cont = FiscalEvent(
            tenant_id=context.tenant_id,
            store_id=sale.store_id,
            fiscal_document_id=doc.id,
            actor_id=actor_id,
            event_type=FiscalEventTypeEnum.CONTINGENCY_REGISTERED,
            details=f"Emitido em Contingência Offline Chave: {access_key}"
        )
        session.add(event_cont)

        reliability_service.write_audit_and_outbox(
            session=session,
            tenant_id=context.tenant_id,
            store_id=sale.store_id,
            actor_id=actor_id,
            action="fiscal.contingency",
            target=f"FISCAL-{doc.id}",
            audit_payload={"fiscal_document_id": str(doc.id), "access_key": access_key, "status": st.value},
            aggregate_type="fiscal_document",
            aggregate_id=str(doc.id),
            event_type="fiscal.contingency",
            outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(sale.store_id), "sale_id": str(sale.id), "access_key": access_key},
            correlation_id=correlation_id
        )

    session.add(doc)
    session.commit()
    session.refresh(doc)
    session.refresh(sale)
    return doc, sale, False


def retry_fiscal_document(
    session: Session, context: TenantContext, fiscal_document_id: uuid.UUID, *,
    actor_id: uuid.UUID, simulate_status: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> FiscalDocument:
    actor_id = resolve_actor(context, actor_id)
    existing = session.exec(scope_tenant_query(select(FiscalDocument).where(
        FiscalDocument.id == fiscal_document_id,
    ), FiscalDocument, context)).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Documento fiscal não encontrado.")
    if existing.status not in {FiscalStatusEnum.PENDING, FiscalStatusEnum.REJECTED, FiscalStatusEnum.CONTINGENCY}:
        raise HTTPException(status_code=409, detail="Documento fiscal não admite reprocessamento neste estado.")
    document_id = existing.id
    sale_id = existing.sale_id
    document_type = existing.document_type
    from_status = existing.status
    attempt = existing.attempt_count + 1

    # A trilha específica da retentativa é gravada ANTES da tentativa, para
    # entrar no mesmo commit que `issue_fiscal_document` executa. Escrita depois,
    # ela ficava em um segundo commit: uma falha entre os dois deixava a
    # tentativa concluída e sem `RETRY_REQUESTED`, que é justamente o que
    # distingue uma retomada de uma primeira emissão. `write_audit_and_outbox`
    # apenas adiciona à sessão, então a ordem é o que decide a atomicidade.
    session.add(FiscalEvent(
        tenant_id=context.tenant_id, store_id=existing.store_id,
        fiscal_document_id=document_id, actor_id=actor_id,
        event_type=FiscalEventTypeEnum.RETRY_REQUESTED,
        details=f"Reprocessamento da tentativa {attempt}, a partir de {from_status.value}",
    ))
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=existing.store_id,
        actor_id=actor_id, action="fiscal.retry", target=f"FISCAL-{document_id}",
        audit_payload={"attempt_count": attempt, "from_status": from_status.value},
        aggregate_type="fiscal_document", aggregate_id=str(document_id),
        event_type="fiscal.retry_requested",
        outbox_payload={"fiscal_document_id": str(document_id), "attempt_count": attempt},
        correlation_id=correlation_id,
    )

    doc, _sale, already = issue_fiscal_document(
        session, context, sale_id=sale_id, actor_id=actor_id,
        document_type=document_type, simulate_status=simulate_status,
        correlation_id=correlation_id,
    )
    if already:
        # O documento virou terminal entre a checagem e o lock: `issue_fiscal_document`
        # retorna sem commit, e nenhuma tentativa aconteceu. Recusar aqui devolve o
        # mesmo 409 da checagem e descarta a trilha pendente, em vez de registrar
        # uma retomada que não ocorreu.
        session.rollback()
        raise HTTPException(status_code=409, detail="Documento fiscal não admite reprocessamento neste estado.")
    if doc.id != document_id:
        raise HTTPException(status_code=500, detail="Contrato fiscal violado: reprocessamento criou outro documento.")
    return doc

def cancel_fiscal_document(
    session: Session,
    context: TenantContext,
    fiscal_document_id: uuid.UUID,
    actor_id: uuid.UUID,
    reason: str,
    correlation_id: Optional[str] = None
) -> FiscalDocument:
    actor_id = resolve_actor(context, actor_id)
    # GATE 13: Formal Fiscal Cancellation Flow
    doc_query = select(FiscalDocument).where(
        FiscalDocument.id == fiscal_document_id,
        FiscalDocument.tenant_id == context.tenant_id
    ).with_for_update()
    doc = session.exec(doc_query).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fiscal document not found for this tenant.")

    if doc.status != FiscalStatusEnum.AUTHORIZED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ONLY_AUTHORIZED_DOCUMENTS_CAN_BE_CANCELED: Cannot cancel document in status '{doc.status}'."
        )

    success, cancel_xml, msg = fiscal_gateway.cancel_document(
        tenant_id=context.tenant_id,
        store_id=doc.store_id,
        access_key=doc.access_key,
        reason=reason
    )

    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Fiscal cancellation failed: {msg}")

    doc.status = FiscalStatusEnum.CANCELED
    doc.canceled_at = datetime.utcnow()
    session.add(doc)

    event_canc = FiscalEvent(
        tenant_id=context.tenant_id,
        store_id=doc.store_id,
        fiscal_document_id=doc.id,
        actor_id=actor_id,
        event_type=FiscalEventTypeEnum.CANCELED,
        details=f"Cancelamento Homologado Motivo: {reason}"
    )
    session.add(event_canc)

    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=doc.store_id,
        actor_id=actor_id,
        action="fiscal.cancel",
        target=f"FISCAL-{doc.id}",
        audit_payload={"fiscal_document_id": str(doc.id), "access_key": doc.access_key, "reason": reason},
        aggregate_type="fiscal_document",
        aggregate_id=str(doc.id),
        event_type="fiscal.canceled",
        outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(doc.store_id), "fiscal_document_id": str(doc.id), "access_key": doc.access_key},
        correlation_id=correlation_id
    )

    session.commit()
    session.refresh(doc)
    return doc
