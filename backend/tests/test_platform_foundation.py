"""Static architecture gates for the platform foundation.

These tests intentionally do not expose Control Plane endpoints before real
authentication exists. They protect the persistence contracts that future
services and migrations depend on.
"""

from sqlalchemy import UniqueConstraint

from app.models import (
    AgentRun,
    AgentToolCall,
    ApprovalRequest,
    AuthIdentity,
    ContextEdge,
    Lead,
    Membership,
    PlatformMembership,
    Sale,
    SalesChannel,
    Store,
    TenantCapability,
    User,
)


def _unique_constraint_names(model) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name
    }


def test_control_commerce_and_intelligence_tables_are_registered():
    assert AuthIdentity.__tablename__ == "auth_identities"
    assert PlatformMembership.__tablename__ == "platform_memberships"
    assert Lead.__tablename__ == "platform_leads"
    assert TenantCapability.__tablename__ == "tenant_capabilities"
    assert SalesChannel.__tablename__ == "sales_channels"
    assert ContextEdge.__tablename__ == "context_edges"
    assert AgentRun.__tablename__ == "agent_runs"
    assert AgentToolCall.__tablename__ == "agent_tool_calls"
    assert ApprovalRequest.__tablename__ == "approval_requests"


def test_membership_and_site_scope_contracts():
    assert Membership.__table__.c.store_id.nullable is True
    assert "uq_user_tenant_store" in _unique_constraint_names(Membership)
    assert "uq_tenant_store_code" in _unique_constraint_names(Store)
    assert User.__table__.c.password_hash.nullable is True
    assert User.__table__.c.password_setup_completed_at.nullable is True
    assert User.__table__.c.onboarding_completed_at.nullable is True


def test_capability_channel_and_agent_idempotency_contracts():
    assert "uq_tenant_capability_key" in _unique_constraint_names(TenantCapability)
    assert "uq_tenant_sales_channel_code" in _unique_constraint_names(SalesChannel)
    assert "uq_agent_run_tool_idempotency" in _unique_constraint_names(AgentToolCall)


def test_sale_is_ready_for_omnichannel_and_offline_sync():
    required_columns = {
        "channel_id",
        "source_type",
        "external_order_id",
        "idempotency_key",
        "fulfillment_type",
        "sync_status",
        "occurred_at",
    }
    assert required_columns.issubset(Sale.__table__.c.keys())
    assert "uq_tenant_channel_external_order" in _unique_constraint_names(Sale)
    assert "uq_tenant_sale_idempotency_key" in _unique_constraint_names(Sale)
