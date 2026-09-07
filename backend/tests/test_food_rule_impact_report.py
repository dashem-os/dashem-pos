"""O levantamento de impacto só pode contar o que esta mudança tirou.

A primeira versão do relatório contava como perda todo tenant que hoje não tem a
jornada de mesa. Isso mistura duas coisas: quem perdeu agora, e quem já estava
recusado antes. Um contrato sem FOOD_SERVICE é o segundo caso — a regra anterior
já o bloqueava —, e contá-lo como impacto atribuiria a esta mudança um bloqueio
alheio, inflando justamente o número que sustenta a decisão de liberar.

Estes testes fixam a distinção sobre dados reais, com a elegibilidade calculada
nas duas regras pelo mesmo caminho de runtime.

Roda no grupo que enxerga o repositório inteiro: o roteiro vive em `scripts/`,
fora do diretório montado no contêiner de desenvolvimento.
"""

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest
from sqlmodel import Session

from activity_fixtures import (
    FOOD_SERVICE, RETAIL, declare_activity, declare_contract_activities,
)
from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.identity import Store, Tenant, TenantStatusEnum
from app.models.platform import EntitlementStatusEnum, TenantCapability


def _report():
    path = Path(__file__).resolve().parents[2] / "scripts" / "food_rule_impact.py"
    if not path.exists():  # pragma: no cover - só fora do repositório completo
        pytest.skip("roteiro de impacto indisponível neste contexto de execução")
    spec = importlib.util.spec_from_file_location("food_rule_impact", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("food_rule_impact", module)
    spec.loader.exec_module(module)
    return module


def _tenant_with_table_capability(session: Session) -> Tenant:
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(
        name=f"Impacto {suffix}", slug=f"impacto-{suffix}", status=TenantStatusEnum.ACTIVE,
    )
    session.add(tenant)
    session.flush()
    session.add(Store(tenant_id=tenant.id, name="Matriz", code=f"IMP-{suffix}"))
    for key in ("catalog", "payments", "table_service"):
        session.add(TenantCapability(
            tenant_id=tenant.id, key=key, enabled=True,
            status=EntitlementStatusEnum.ACTIVE,
        ))
    session.commit()
    return tenant


def test_a_contract_without_food_service_is_a_pre_existing_block_not_an_impact():
    """Ele já era recusado pela regra anterior; esta mudança não o tirou de nada."""
    report = _report()
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = _tenant_with_table_capability(session)
        declare_contract_activities(session, tenant.id, (RETAIL,))

        linha = report.evaluate(session, tenant)

    assert linha["origem"] == "contrato"
    assert linha["elegivel_antes"] is False, (
        "um contrato sem FOOD_SERVICE já era bloqueado pela regra anterior"
    )
    assert linha["elegivel_depois"] is False
    assert linha["classificacao"] == report.BLOQUEIO_PREEXISTENTE


def test_a_legacy_tenant_with_nothing_declared_is_the_real_impact():
    """Antes passava por ausência de contrato; agora responde pelo perfil."""
    report = _report()
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = _tenant_with_table_capability(session)

        linha = report.evaluate(session, tenant)

    assert linha["origem"] == "legado"
    assert linha["elegivel_antes"] is True
    assert linha["elegivel_depois"] is False
    assert linha["classificacao"] == report.IMPACTO


def test_a_tenant_that_keeps_the_journey_is_never_counted():
    """Nem impacto, nem bloqueio: quem continua atendendo mesa fica de fora."""
    report = _report()
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = _tenant_with_table_capability(session)
        declare_activity(session, tenant.id, FOOD_SERVICE)

        linha = report.evaluate(session, tenant)

    assert linha["elegivel_antes"] is True and linha["elegivel_depois"] is True
    assert linha["classificacao"] == report.MANTEM


def test_a_mixed_contract_with_food_service_keeps_the_journey():
    """Varejo e food service juntos não são impacto nenhum."""
    report = _report()
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = _tenant_with_table_capability(session)
        declare_contract_activities(session, tenant.id, (RETAIL, FOOD_SERVICE))

        linha = report.evaluate(session, tenant)

    assert linha["classificacao"] == report.MANTEM


@pytest.mark.parametrize(
    ("antes", "depois", "esperado"),
    [
        (True, False, "impacto"),
        (False, False, "bloqueio_preexistente"),
        (True, True, "mantem"),
        # Ganhar acesso não é impacto desta mudança, e também não é bloqueio.
        (False, True, "mantem"),
    ],
)
def test_the_classification_counts_only_what_this_change_removed(antes, depois, esperado):
    report = _report()
    assert report.classify(antes, depois) == esperado


def test_the_report_keeps_no_write_path_it_once_had():
    """Guarda de regressão sobre o fonte — **não** é prova de ausência de escrita.

    A versão anterior tinha modo de regularização: ele atribuía a decisão ao
    primeiro usuário do banco e escrevia direto na atribuição de perfil, sem
    passar pelo fluxo que valida a revisão e responde por um ator autenticado.

    Este teste procura as marcas daquele modo. Um fonte pode escrever no banco
    sem nenhuma delas — por SQL cru, por outro helper —, então o que ele oferece
    é um alarme barato contra a volta do mesmo padrão, e nada além disso.
    """
    path = Path(__file__).resolve().parents[2] / "scripts" / "food_rule_impact.py"
    if not path.exists():  # pragma: no cover
        pytest.skip("roteiro de impacto indisponível neste contexto de execução")
    source = path.read_text(encoding="utf-8")
    for proibido in ("session.add(", "session.commit()", "--regularize", "assigned_by"):
        assert proibido not in source, f"o levantamento voltou a escrever: {proibido}"
