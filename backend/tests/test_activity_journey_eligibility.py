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


def test_a_legacy_tenant_that_declared_nothing_does_not_get_the_table_journey():
    """O tenant legado deixou de ser exceção à regra.

    Ele era: sem contrato versionado, a jornada de mesa passava. O efeito prático
    disso era perverso — quem nunca declarou atividade nenhuma tinha mais acesso
    do que quem declarou varejo. Agora ele responde pelo que declarou no perfil
    de capability, e não tendo declarado nada, a jornada é recusada.
    """
    with patch(
        "app.modules.capabilities.service.resolve_contract_entitlements",
        return_value=None,
    ), patch(
        "app.modules.capabilities.service.tenant_activity_keys",
        return_value=(),
    ):
        assert not capability_allowed_by_activity(object(), object(), "table_service")


def test_a_legacy_tenant_declares_its_activity_through_the_capability_profile():
    """Sem contrato, a atividade vem do perfil — a mesma fonte que o Owner lê."""
    from app.modules.capabilities import service as capability_service

    with patch(
        "app.modules.capabilities.service.resolve_contract_entitlements",
        return_value=None,
    ), patch.object(
        capability_service, "tenant_activity_keys", return_value=("FOOD_SERVICE",),
    ):
        assert capability_allowed_by_activity(object(), object(), "table_service")


def test_the_rule_only_governs_the_table_journey():
    """Nenhuma outra capability é afetada por atividade nesta regra."""
    with patch(
        "app.modules.capabilities.service.resolve_contract_entitlements",
        return_value=SimpleNamespace(activity_keys=("BEAUTY_RESELLER",)),
    ):
        for key in ("catalog", "payments", "counter_order", "delivery_orders"):
            assert capability_allowed_by_activity(object(), object(), key)
