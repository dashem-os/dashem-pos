from types import SimpleNamespace
from unittest.mock import patch

from app.modules.capabilities.service import capability_allowed_by_activity


def test_table_journey_requires_food_service_activity():
    tenant_id = object()
    with patch(
        "app.modules.capabilities.service.resolve_contract_entitlements",
        return_value=SimpleNamespace(activity_keys=("RETAIL",)),
    ):
        assert not capability_allowed_by_activity(object(), tenant_id, "table_service")


def test_hybrid_food_service_activity_keeps_table_journey_eligible():
    tenant_id = object()
    with patch(
        "app.modules.capabilities.service.resolve_contract_entitlements",
        return_value=SimpleNamespace(activity_keys=("RETAIL", "FOOD_SERVICE")),
    ):
        assert capability_allowed_by_activity(object(), tenant_id, "table_service")


def test_pre_contract_legacy_capabilities_remain_explicitly_compatible():
    with patch(
        "app.modules.capabilities.service.resolve_contract_entitlements",
        return_value=None,
    ):
        assert capability_allowed_by_activity(object(), object(), "table_service")
