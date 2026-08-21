"""Platform, multi-site, omnichannel and agent-ready foundation.

Revision ID: 009_platform_foundation
Revises: 008_fiscal_request_hash
Create Date: 2026-08-21 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "009_platform_foundation"
down_revision: Union[str, None] = "008_fiscal_request_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tenant and site lifecycle. String values are intentional: application
    # enums can evolve without PostgreSQL enum migrations.
    op.add_column("tenants", sa.Column("status", sa.String(), nullable=False, server_default="PROVISIONING"))
    op.add_column("tenants", sa.Column("legal_name", sa.String(), nullable=True))
    op.add_column("tenants", sa.Column("timezone", sa.String(), nullable=False, server_default="America/Sao_Paulo"))
    op.add_column("tenants", sa.Column("default_locale", sa.String(), nullable=False, server_default="pt-BR"))
    op.add_column("tenants", sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
    op.create_index(op.f("ix_tenants_status"), "tenants", ["status"], unique=False)

    op.add_column("stores", sa.Column("site_type", sa.String(), nullable=False, server_default="STORE"))
    op.add_column("stores", sa.Column("timezone", sa.String(), nullable=False, server_default="America/Sao_Paulo"))
    op.add_column("stores", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("stores", sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
    op.create_index(op.f("ix_stores_site_type"), "stores", ["site_type"], unique=False)
    op.create_index(op.f("ix_stores_is_active"), "stores", ["is_active"], unique=False)
    op.create_unique_constraint("uq_tenant_store_code", "stores", ["tenant_id", "code"])

    # A NULL store_id is a tenant-wide membership. The partial unique index
    # prevents duplicate tenant-wide memberships while retaining the existing
    # site-scoped uniqueness constraint.
    op.alter_column("memberships", "store_id", existing_type=sa.UUID(), nullable=True)
    op.add_column("memberships", sa.Column("status", sa.String(), nullable=False, server_default="ACTIVE"))
    op.add_column("memberships", sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
    op.create_index(op.f("ix_memberships_status"), "memberships", ["status"], unique=False)
    op.create_index(
        "uq_user_tenant_membership_all_sites",
        "memberships",
        ["user_id", "tenant_id"],
        unique=True,
        postgresql_where=sa.text("store_id IS NULL"),
    )

    op.create_table(
        "platform_memberships",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_platform_membership_user"),
    )
    op.create_index(op.f("ix_platform_memberships_user_id"), "platform_memberships", ["user_id"])
    op.create_index(op.f("ix_platform_memberships_role"), "platform_memberships", ["role"])
    op.create_index(op.f("ix_platform_memberships_is_active"), "platform_memberships", ["is_active"])

    op.create_table(
        "platform_leads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("contact_name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="NEW"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("converted_tenant_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("converted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["converted_tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("company_name", "email", "phone", "source", "status", "owner_user_id", "converted_tenant_id", "created_at"):
        op.create_index(op.f(f"ix_platform_leads_{column}"), "platform_leads", [column])

    op.create_table(
        "tenant_capabilities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("configuration", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_tenant_capability_key"),
    )
    op.create_index(op.f("ix_tenant_capabilities_tenant_id"), "tenant_capabilities", ["tenant_id"])
    op.create_index(op.f("ix_tenant_capabilities_key"), "tenant_capabilities", ["key"])
    op.create_index(op.f("ix_tenant_capabilities_enabled"), "tenant_capabilities", ["enabled"])

    op.create_table(
        "sales_channels",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("store_id", sa.UUID(), nullable=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("channel_type", sa.String(), nullable=False),
        sa.Column("external_account_id", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("configuration", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_tenant_sales_channel_code"),
    )
    for column in ("tenant_id", "store_id", "code", "name", "channel_type", "external_account_id", "is_active"):
        op.create_index(op.f(f"ix_sales_channels_{column}"), "sales_channels", [column])

    # Omnichannel and offline-safe sales metadata. Existing sales are POS,
    # counter fulfillment and already synchronized.
    op.add_column("sales", sa.Column("channel_id", sa.UUID(), nullable=True))
    op.add_column("sales", sa.Column("source_type", sa.String(), nullable=False, server_default="POS"))
    op.add_column("sales", sa.Column("external_order_id", sa.String(), nullable=True))
    op.add_column("sales", sa.Column("idempotency_key", sa.String(), nullable=True))
    op.add_column("sales", sa.Column("fulfillment_type", sa.String(), nullable=False, server_default="COUNTER"))
    op.add_column("sales", sa.Column("sync_status", sa.String(), nullable=False, server_default="SYNCED"))
    op.add_column("sales", sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
    op.create_foreign_key("fk_sales_channel_id", "sales", "sales_channels", ["channel_id"], ["id"])
    for column in ("channel_id", "source_type", "external_order_id", "idempotency_key", "fulfillment_type", "sync_status", "occurred_at"):
        op.create_index(op.f(f"ix_sales_{column}"), "sales", [column])
    op.create_unique_constraint(
        "uq_tenant_channel_external_order",
        "sales",
        ["tenant_id", "channel_id", "external_order_id"],
    )
    op.create_unique_constraint(
        "uq_tenant_sale_idempotency_key",
        "sales",
        ["tenant_id", "idempotency_key"],
    )

    # Reliability metadata becomes rich enough to feed projections and graph
    # context without changing the established outbox workflow.
    op.add_column("outbox_events", sa.Column("store_id", sa.UUID(), nullable=True))
    op.add_column("outbox_events", sa.Column("actor_id", sa.UUID(), nullable=True))
    op.add_column("outbox_events", sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("outbox_events", sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
    op.create_index(op.f("ix_outbox_events_store_id"), "outbox_events", ["store_id"])
    op.create_index(op.f("ix_outbox_events_actor_id"), "outbox_events", ["actor_id"])
    op.create_index(op.f("ix_outbox_events_occurred_at"), "outbox_events", ["occurred_at"])

    op.alter_column("audit_events", "tenant_id", existing_type=sa.UUID(), nullable=True)
    op.alter_column("audit_events", "store_id", existing_type=sa.UUID(), nullable=True)
    op.add_column("audit_events", sa.Column("platform_scope", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index(op.f("ix_audit_events_platform_scope"), "audit_events", ["platform_scope"])

    op.create_table(
        "context_edges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("store_id", sa.UUID(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("relation", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=False),
        sa.Column("provenance", sa.String(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "source_type", "source_id", "relation", "target_type", "target_id", name="uq_tenant_context_edge"),
    )
    for column in ("tenant_id", "store_id", "source_type", "source_id", "relation", "target_type", "target_id", "provenance", "occurred_at", "created_at"):
        op.create_index(op.f(f"ix_context_edges_{column}"), "context_edges", [column])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("store_id", sa.UUID(), nullable=True),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("agent_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("model_version", sa.String(), nullable=True),
        sa.Column("input_context", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("tenant_id", "store_id", "actor_id", "agent_key", "status", "model", "correlation_id", "created_at"):
        op.create_index(op.f(f"ix_agent_runs_{column}"), "agent_runs", [column])

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("store_id", sa.UUID(), nullable=True),
        sa.Column("agent_run_id", sa.UUID(), nullable=False),
        sa.Column("tool_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="REQUESTED"),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_run_id", "idempotency_key", name="uq_agent_run_tool_idempotency"),
    )
    for column in ("tenant_id", "store_id", "agent_run_id", "tool_key", "status", "idempotency_key", "requested_at"):
        op.create_index(op.f(f"ix_agent_tool_calls_{column}"), "agent_tool_calls", [column])

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("store_id", sa.UUID(), nullable=True),
        sa.Column("agent_run_id", sa.UUID(), nullable=True),
        sa.Column("tool_call_id", sa.UUID(), nullable=True),
        sa.Column("requested_by_id", sa.UUID(), nullable=False),
        sa.Column("decided_by_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"]),
        sa.ForeignKeyConstraint(["tool_call_id"], ["agent_tool_calls.id"]),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("tenant_id", "store_id", "agent_run_id", "tool_call_id", "requested_by_id", "decided_by_id", "action", "status", "expires_at", "created_at"):
        op.create_index(op.f(f"ix_approval_requests_{column}"), "approval_requests", [column])


def downgrade() -> None:
    op.drop_table("approval_requests")
    op.drop_table("agent_tool_calls")
    op.drop_table("agent_runs")
    op.drop_table("context_edges")

    op.drop_index(op.f("ix_audit_events_platform_scope"), table_name="audit_events")
    op.drop_column("audit_events", "platform_scope")
    op.alter_column("audit_events", "store_id", existing_type=sa.UUID(), nullable=False)
    op.alter_column("audit_events", "tenant_id", existing_type=sa.UUID(), nullable=False)

    op.drop_index(op.f("ix_outbox_events_occurred_at"), table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_actor_id"), table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_store_id"), table_name="outbox_events")
    for column in ("occurred_at", "schema_version", "actor_id", "store_id"):
        op.drop_column("outbox_events", column)

    op.drop_constraint("uq_tenant_sale_idempotency_key", "sales", type_="unique")
    op.drop_constraint("uq_tenant_channel_external_order", "sales", type_="unique")
    for column in ("occurred_at", "sync_status", "fulfillment_type", "idempotency_key", "external_order_id", "source_type", "channel_id"):
        op.drop_index(op.f(f"ix_sales_{column}"), table_name="sales")
    op.drop_constraint("fk_sales_channel_id", "sales", type_="foreignkey")
    for column in ("occurred_at", "sync_status", "fulfillment_type", "idempotency_key", "external_order_id", "source_type", "channel_id"):
        op.drop_column("sales", column)

    op.drop_table("sales_channels")
    op.drop_table("tenant_capabilities")
    op.drop_table("platform_leads")
    op.drop_table("platform_memberships")

    op.drop_index("uq_user_tenant_membership_all_sites", table_name="memberships")
    op.drop_index(op.f("ix_memberships_status"), table_name="memberships")
    op.drop_column("memberships", "updated_at")
    op.drop_column("memberships", "status")
    op.alter_column("memberships", "store_id", existing_type=sa.UUID(), nullable=False)

    op.drop_constraint("uq_tenant_store_code", "stores", type_="unique")
    op.drop_index(op.f("ix_stores_is_active"), table_name="stores")
    op.drop_index(op.f("ix_stores_site_type"), table_name="stores")
    for column in ("updated_at", "is_active", "timezone", "site_type"):
        op.drop_column("stores", column)

    op.drop_index(op.f("ix_tenants_status"), table_name="tenants")
    for column in ("updated_at", "default_locale", "timezone", "legal_name", "status"):
        op.drop_column("tenants", column)
