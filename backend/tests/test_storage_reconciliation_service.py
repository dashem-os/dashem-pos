from datetime import datetime, timedelta
from uuid import uuid4

from app.core.config import settings
from app.models.storage import StorageMeterSource
from app.services.storage_reconciliation_service import configure_supabase_sources


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class _SourceSession:
    def __init__(self, existing=None):
        self._existing = iter(existing or [None] * len(settings.supabase_storage_buckets))
        self.added = []
        self.flushed = False

    def exec(self, _query):
        return _ScalarResult(next(self._existing))

    def add(self, source):
        self.added.append(source)

    def flush(self):
        self.flushed = True


def test_new_sources_share_the_reconciliation_timestamp():
    measured_at = datetime(2026, 8, 31, 23, 59, 40)
    session = _SourceSession()

    sources = configure_supabase_sources(
        session, uuid4(), uuid4(), now=measured_at
    )

    assert session.flushed is True
    assert len(session.added) == len(settings.supabase_storage_buckets)
    assert all(source.created_at == measured_at for source in sources)
    assert all(source.updated_at == measured_at for source in sources)


def test_unchanged_sources_do_not_invalidate_a_fresh_inventory():
    tenant_id = uuid4()
    actor_id = uuid4()
    original = datetime(2026, 8, 31, 23, 0, 0)
    measured_at = original + timedelta(hours=1)
    sources = [
        StorageMeterSource(
            tenant_id=tenant_id,
            source_key=f"supabase:{bucket}",
            provider="SUPABASE",
            locator_reference=f"{bucket}/{tenant_id}",
            status="ACTIVE",
            created_by=actor_id,
            created_at=original,
            updated_at=original,
        )
        for bucket in settings.supabase_storage_buckets
    ]
    session = _SourceSession(sources)

    configured = configure_supabase_sources(
        session, tenant_id, actor_id, now=measured_at
    )

    assert configured == sources
    assert session.added == []
    assert all(source.updated_at == original for source in configured)
