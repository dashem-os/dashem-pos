import pytest

from app.services.commercial_offer_service import (
    ActivityRule,
    CommercialOfferError,
    compose_commercial_offer,
)


def _rules() -> list[ActivityRule]:
    return [
        ActivityRule("RETAIL", "catalog", "REQUIRED", True),
        ActivityRule("RETAIL", "inventory", "REQUIRED", True),
        ActivityRule("RETAIL", "receivables", "OPTIONAL", False),
        ActivityRule("FOOD_SERVICE", "catalog", "REQUIRED", True),
        ActivityRule("FOOD_SERVICE", "counter_order", "REQUIRED", True),
        ActivityRule("FOOD_SERVICE", "table_service", "OPTIONAL", False),
    ]


def test_offer_combines_plan_and_multiple_activities_without_authorizing_tenant():
    proposal = compose_commercial_offer(
        plan_capability_keys=(
            "catalog", "inventory", "receivables", "counter_order", "table_service"
        ),
        plan_activity_keys=("RETAIL", "FOOD_SERVICE"),
        selected_activity_keys=("RETAIL", "FOOD_SERVICE"),
        requested_addon_keys=("receivables", "table_service"),
        rules=_rules(),
    )

    assert proposal["authorizes_tenant"] is False
    assert proposal["activity_keys"] == ["RETAIL", "FOOD_SERVICE"]
    assert set(proposal["capability_keys"]) == {
        "catalog", "inventory", "receivables", "counter_order", "table_service"
    }
    receivables = next(
        item for item in proposal["capabilities"] if item["key"] == "receivables"
    )
    assert set(receivables["sources"]) == {"PLAN", "ADDON"}


def test_offer_exposes_required_capability_gap_instead_of_granting_it():
    proposal = compose_commercial_offer(
        plan_capability_keys=("catalog",),
        plan_activity_keys=("RETAIL",),
        selected_activity_keys=("RETAIL",),
        rules=_rules(),
    )

    assert proposal["capability_keys"] == ["catalog"]
    assert proposal["gaps"] == [
        {
            "key": "inventory",
            "name": "Estoque",
            "reason": "REQUIRED_NOT_INCLUDED_IN_PLAN",
        }
    ]


def test_offer_rejects_activity_not_supported_by_plan():
    with pytest.raises(CommercialOfferError, match="incompatíveis"):
        compose_commercial_offer(
            plan_capability_keys=("catalog",),
            plan_activity_keys=("RETAIL",),
            selected_activity_keys=("FOOD_SERVICE",),
            rules=_rules(),
        )
