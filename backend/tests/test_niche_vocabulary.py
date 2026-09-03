"""The console speaks the vocabulary of the contracted activity.

A beauty reseller has no menus. The navigation label for the assortment module
follows the contract instead of assuming food service for every tenant.
"""

import pytest

from app.api.v1.endpoints.capabilities import _labelled
from app.models.platform import ModuleContribution


def _assortments_contribution() -> ModuleContribution:
    return ModuleContribution(
        contribution_key="assortments",
        label="Sortimentos e cardápios",
        surface="MANAGEMENT_NAV",
        group_key="MERCADORIAS",
        route="/manage/assortments",
        sort_order=10,
        is_active=True,
    )


@pytest.mark.parametrize(
    "activities,expected",
    [
        ({"FOOD_SERVICE"}, "Sortimentos e cardápios"),
        ({"FOOD_SERVICE", "RETAIL"}, "Sortimentos e cardápios"),
        ({"RETAIL"}, "Sortimentos e catálogos"),
        ({"BEAUTY_RESELLER"}, "Sortimentos e catálogos"),
        (set(), "Sortimentos e catálogos"),
    ],
)
def test_assortment_label_follows_the_contracted_activity(activities: set[str], expected: str):
    assert _labelled(_assortments_contribution(), activities).label == expected


def test_other_modules_keep_their_label():
    contribution = ModuleContribution(
        contribution_key="customers",
        label="Clientes",
        surface="MANAGEMENT_NAV",
        group_key="RELACIONAMENTO",
        route="/manage/customers",
        sort_order=20,
        is_active=True,
    )
    assert _labelled(contribution, {"BEAUTY_RESELLER"}).label == "Clientes"
