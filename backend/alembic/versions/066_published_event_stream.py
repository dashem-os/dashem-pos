"""Create the immutable internal event stream consumed from the outbox.

Revision ID: 066_published_event_stream
Revises: 065_supabase_storage
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "066_published_event_stream"
down_revision = "065_supabase_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "published_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outbox_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("aggregate_type", sa.String(), nullable=False),
        sa.Column("aggregate_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("schema_version > 0", name="ck_published_events_schema_version"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_published_events_content_hash"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outbox_event_id", name="uq_published_events_outbox_event_id"),
    )
    for column in (
        "outbox_event_id", "tenant_id", "store_id", "actor_id", "aggregate_type",
        "aggregate_id", "event_type", "content_hash", "correlation_id", "occurred_at", "published_at",
    ):
        op.create_index(f"ix_published_events_{column}", "published_events", [column])

    op.execute("ALTER TABLE published_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE published_events FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY published_events_select ON published_events FOR SELECT USING (
            current_setting('app.platform_access', true) = 'true'
            OR (
                tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                AND (
                    nullif(current_setting('app.store_id', true), '') IS NULL
                    OR store_id IS NULL
                    OR store_id = nullif(current_setting('app.store_id', true), '')::uuid
                )
            )
        )
    """)
    op.execute("""
        CREATE POLICY published_events_platform_insert ON published_events FOR INSERT
        WITH CHECK (current_setting('app.platform_access', true) = 'true')
    """)
    op.execute("""
        CREATE FUNCTION protect_published_event() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$ BEGIN
            RAISE EXCEPTION 'published events are immutable';
        END; $$
    """)
    op.execute("""
        CREATE TRIGGER published_events_immutable BEFORE UPDATE OR DELETE ON published_events
        FOR EACH ROW EXECUTE FUNCTION protect_published_event()
    """)
    op.execute("GRANT SELECT, INSERT ON published_events TO dashem_runtime")


def downgrade() -> None:
    op.execute("DROP TRIGGER published_events_immutable ON published_events")
    op.execute("DROP FUNCTION protect_published_event()")
    op.drop_table("published_events")
