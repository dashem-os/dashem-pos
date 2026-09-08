"""The console speaks the vocabulary of the contracted activity.

A beauty reseller has no menus. The navigation label for the assortment module
follows the contract instead of assuming food service for every tenant.
"""

import pytest

from app.api.v1.endpoints.capabilities import _labelled
from app.models.platform import ModuleContribution


def _assortments_contribution() -> ModuleContribution:
    """A linha como a malha a guarda depois da 088.

    O rótulo base é o neutro e a palavra do nicho é dado da própria
    contribuição, não uma exceção conhecida pelo código de projeção.
    """
    return ModuleContribution(
        contribution_key="assortments",
        label="Catálogos",
        surface="MANAGEMENT_NAV",
        group_key="MERCADORIAS",
        route="/manage/assortments",
        sort_order=10,
        is_active=True,
        metadata_json={
            "label_variants": [{"when_activity": "FOOD_SERVICE", "label": "Cardápios"}],
        },
    )


@pytest.mark.parametrize(
    "activities,expected",
    [
        ({"FOOD_SERVICE"}, "Cardápios"),
        ({"FOOD_SERVICE", "RETAIL"}, "Cardápios"),
        ({"RETAIL"}, "Catálogos"),
        ({"BEAUTY_RESELLER"}, "Catálogos"),
        (set(), "Catálogos"),
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


def test_a_contribution_without_variants_keeps_its_label():
    """Sem variante declarada, atividade nenhuma muda a palavra."""
    contribution = ModuleContribution(
        contribution_key="assortments", label="Catálogos", surface="MANAGEMENT_NAV",
        implementation_key="AssortmentManager",
    )
    assert _labelled(contribution, {"FOOD_SERVICE"}).label == "Catálogos"


def test_the_first_matching_variant_wins():
    """A lista é ordem de precedência, para o desempate ser explícito."""
    contribution = ModuleContribution(
        contribution_key="assortments", label="Catálogos", surface="MANAGEMENT_NAV",
        implementation_key="AssortmentManager",
        metadata_json={"label_variants": [
            {"when_activity": "FOOD_SERVICE", "label": "Cardápios"},
            {"when_activity": "RETAIL", "label": "Vitrines"},
        ]},
    )
    assert _labelled(contribution, {"RETAIL", "FOOD_SERVICE"}).label == "Cardápios"
    assert _labelled(contribution, {"RETAIL"}).label == "Vitrines"
