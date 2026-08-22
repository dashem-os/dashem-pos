import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.identity import Store, Tenant, TenantStatusEnum
from app.models.catalog import Product
from app.models.sale import Sale, SaleItem
from app.models.platform import StoreCapabilityOverride
from app.modules.capabilities.registry import CAPABILITY_REGISTRY, resolve_dependencies


def test_capability_graph_resolves_dependencies_before_dependents():
    resolved = resolve_dependencies(["high_speed_checkout", "fiscal_nfce"])
    assert resolved.index("catalog") < resolved.index("barcode_scanning")
    assert resolved.index("barcode_scanning") < resolved.index("high_speed_checkout")
    assert resolved.index("payments") < resolved.index("fiscal_nfce")
    assert len(resolved) == len(set(resolved))
    assert all(contract.version == "1.0.0" for contract in CAPABILITY_REGISTRY.values())


def test_unknown_capability_is_rejected():
    try:
        resolve_dependencies(["imaginary_capability"])
        assert False, "Unknown capabilities must fail closed"
    except KeyError:
        pass


def test_every_tenant_table_is_forced_through_rls():
    """Prevent a future tenant table from silently bypassing the DB boundary."""
    with Session(engine) as session:
        runtime = session.exec(text("""
            SELECT current_user, rolbypassrls, rolsuper
            FROM pg_roles
            WHERE rolname = current_user
        """)).one()
        assert runtime[0] == "dashem_runtime"
        assert runtime[1] is False
        assert runtime[2] is False

        tenant_tables = session.exec(text("""
            SELECT DISTINCT c.relname, c.relrowsecurity, c.relforcerowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_attribute a
              ON a.attrelid = c.oid
             AND a.attname = 'tenant_id'
             AND NOT a.attisdropped
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND (a.attname IS NOT NULL OR c.relname = 'tenants')
            ORDER BY c.relname
        """)).all()
        assert tenant_tables, "No tenant-owned tables were discovered"
        assert all(row[1] and row[2] for row in tenant_tables), tenant_tables

        policy_tables = {
            row[0] for row in session.exec(text("""
                SELECT DISTINCT tablename
                FROM pg_policies
                WHERE schemaname = 'public'
            """)).all()
        }
        missing = {row[0] for row in tenant_tables} - policy_tables
        assert not missing, f"Tenant tables without an RLS policy: {sorted(missing)}"


def test_postgres_rls_denies_neighbor_tenant_and_store():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant_a = Tenant(name=f"RLS A {suffix}", slug=f"rls-a-{suffix}", status=TenantStatusEnum.ACTIVE)
        tenant_b = Tenant(name=f"RLS B {suffix}", slug=f"rls-b-{suffix}", status=TenantStatusEnum.ACTIVE)
        session.add(tenant_a)
        session.add(tenant_b)
        session.flush()
        store_a1 = Store(tenant_id=tenant_a.id, name="A1", code=f"A1-{suffix}")
        store_a2 = Store(tenant_id=tenant_a.id, name="A2", code=f"A2-{suffix}")
        store_b = Store(tenant_id=tenant_b.id, name="B1", code=f"B1-{suffix}")
        session.add(store_a1)
        session.add(store_a2)
        session.add(store_b)
        tenant_a_id, tenant_b_id = tenant_a.id, tenant_b.id
        store_a1_id, store_a2_id, store_b_id = store_a1.id, store_a2.id, store_b.id
        session.commit()

    with Session(engine) as session:
        set_tenant_db_context(session, tenant_a_id, store_a1_id)
        db_context = session.exec(text("""
            SELECT current_setting('app.platform_access', true),
                   current_setting('app.tenant_id', true),
                   current_setting('app.store_id', true),
                   current_user
        """)).one()
        assert db_context == (
            "false", str(tenant_a_id), str(store_a1_id), "dashem_runtime"
        )
        assert session.get(Tenant, tenant_a_id) is not None
        assert session.get(Tenant, tenant_b_id) is None
        visible_store_ids = {store.id for store in session.exec(select(Store)).all()}
        assert visible_store_ids == {store_a1_id}
        assert store_a2_id not in visible_store_ids
        assert store_b_id not in visible_store_ids

    with Session(engine) as session:
        # A tenant-wide administrator may address all of its own sites, but
        # the database must reject a sibling tenant's site even if IDs are
        # combined manually or an application validation is accidentally lost.
        set_tenant_db_context(session, tenant_a_id)
        session.add(StoreCapabilityOverride(
            tenant_id=tenant_a_id,
            store_id=store_b_id,
            key="catalog",
            enabled=True,
        ))
        with pytest.raises(DBAPIError):
            session.commit()


def test_sale_items_inherit_the_parent_sale_site_boundary():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"Line isolation {suffix}", slug=f"line-isolation-{suffix}", status=TenantStatusEnum.ACTIVE)
        session.add(tenant)
        session.flush()
        store_a = Store(tenant_id=tenant.id, name="Site A", code=f"SA-{suffix}")
        store_b = Store(tenant_id=tenant.id, name="Site B", code=f"SB-{suffix}")
        product = Product(tenant_id=tenant.id, name="Shared catalog item", sku=f"SKU-{suffix}")
        session.add(store_a)
        session.add(store_b)
        session.add(product)
        session.flush()
        sale_a = Sale(tenant_id=tenant.id, store_id=store_a.id)
        sale_b = Sale(tenant_id=tenant.id, store_id=store_b.id)
        session.add(sale_a)
        session.add(sale_b)
        session.flush()
        line_a = SaleItem(
            tenant_id=tenant.id, sale_id=sale_a.id, product_id=product.id,
            product_name=product.name, sku=product.sku, unit_price=Decimal("10"),
            quantity=Decimal("1"), gross_total=Decimal("10"), net_total=Decimal("10"),
        )
        line_b = SaleItem(
            tenant_id=tenant.id, sale_id=sale_b.id, product_id=product.id,
            product_name=product.name, sku=product.sku, unit_price=Decimal("10"),
            quantity=Decimal("1"), gross_total=Decimal("10"), net_total=Decimal("10"),
        )
        session.add(line_a)
        session.add(line_b)
        tenant_id, store_a_id = tenant.id, store_a.id
        line_a_id, line_b_id = line_a.id, line_b.id
        session.commit()

    with Session(engine) as session:
        set_tenant_db_context(session, tenant_id, store_a_id)
        visible_line_ids = {line.id for line in session.exec(select(SaleItem)).all()}
        assert visible_line_ids == {line_a_id}
        assert line_b_id not in visible_line_ids
