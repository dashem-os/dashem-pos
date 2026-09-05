"""Server-owned storage preparation for an authenticated catalog editor.

Only the authenticated tenant and fixed, private bucket names are accepted.
The maintenance session records provider facts; it never reads media content,
changes contracts, or lends platform database authority to the request session.
"""

from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.core.context import TenantContext, resolve_actor
from app.core.tenancy import set_platform_db_context
from app.services.storage_quota_service import (
    evaluate_platform_storage_capacity, evaluate_tenant_storage_quota,
    storage_quota_read_model, provider_capacity_read_model,
)
from app.services.storage_reconciliation_service import reconcile_supabase_storage
from app.services.supabase_storage import SupabaseStorageClient, SupabaseStorageUnavailable


def prepare_catalog_storage(session: Session, context: TenantContext) -> dict:
    actor_id = resolve_actor(context)
    if not settings.supabase_storage_configured:
        raise SupabaseStorageUnavailable(
            "O armazenamento de imagens não está configurado na plataforma. "
            "A equipe DASHEM precisa configurar o provedor e sua capacidade."
        )
    state = storage_quota_read_model(session, context.tenant_id)
    if state['status_code'] == 'NO_CONTRACT_QUOTA':
        return state | {'upload_available': False, 'upload_reason': 'O contrato do negócio ainda não possui cota de imagens.'}

    provider_state = provider_capacity_read_model(session)
    if state['status_code'] != 'READY' or provider_state['measurement_status'] != 'RECONCILED':
        with Session(session.get_bind()) as maintenance:
            set_platform_db_context(maintenance, actor_id)
            # Serialize preparation across tenants sharing this physical provider.
            maintenance.exec(text("SELECT pg_advisory_xact_lock(73492108)"))
            current = storage_quota_read_model(maintenance, context.tenant_id)
            provider = provider_capacity_read_model(maintenance)
            if current['status_code'] != 'READY' or provider['measurement_status'] != 'RECONCILED':
                client = SupabaseStorageClient()
                client.ensure_private_buckets()
                reconcile_supabase_storage(maintenance, context.tenant_id, actor_id, client=client)
                maintenance.commit()

    state, tenant_decision = evaluate_tenant_storage_quota(session, context.tenant_id, requested_bytes=1)
    _, provider_decision = evaluate_platform_storage_capacity(session, requested_bytes=1)
    decisions = (tenant_decision, provider_decision)
    blocked = next((item for item in decisions if item.decision.value not in {'ALLOWED', 'WARNING'}), None)
    return state | {'upload_available': blocked is None, 'upload_reason': blocked.reason if blocked else None}
