"""O diagnóstico precisa achar a marca do defeito e não pode encostar no dado.

O roteiro existe para uma decisão sobre dados reais: quem foi atingido pelo
defeito de sinal e pela falha transacional, e o que fazer com cada caso. Isso
impõe duas exigências opostas — enxergar o suficiente para sustentar a decisão,
e não alterar nada enquanto enxerga.

Estes testes plantam cada assinatura no banco e conferem que ela é encontrada.
A linha com saída positiva é escrita direto no modelo, porque o serviço
corrigido recusa produzi-la: é exatamente esse o ponto do levantamento, achar o
que ficou de antes da correção.

Roda no grupo que enxerga o repositório inteiro: o roteiro vive em `scripts/`,
fora do diretório montado no contêiner de desenvolvimento.
"""

import importlib.util
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.catalog import (
    InventoryBalance, InventoryMovement, MovementTypeEnum, Product,
)
from app.models.identity import Store, Tenant, TenantStatusEnum


def _diagnosis():
    path = Path(__file__).resolve().parents[2] / "scripts" / "inventory_integrity_diagnosis.py"
    if not path.exists():  # pragma: no cover - só fora do repositório completo
        pytest.skip("roteiro de diagnóstico indisponível neste contexto de execução")
    spec = importlib.util.spec_from_file_location("inventory_integrity_diagnosis", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("inventory_integrity_diagnosis", module)
    spec.loader.exec_module(module)
    return module


def _store(session: Session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    suffix = uuid.uuid4().hex[:8]
    set_platform_db_context(session)
    tenant = Tenant(
        name=f"Diagnóstico {suffix}", slug=f"diagnostico-{suffix}",
        status=TenantStatusEnum.ACTIVE,
    )
    session.add(tenant)
    session.flush()
    store = Store(tenant_id=tenant.id, name="Matriz", code=f"DIA-{suffix}")
    session.add(store)
    session.commit()
    set_tenant_db_context(session, tenant.id, store.id, None)
    product = Product(
        tenant_id=tenant.id, name=f"Mercadoria {suffix}", sku=f"DIA-{suffix}",
    )
    session.add(product)
    session.commit()
    return tenant.id, store.id, product.id


def _findings(tipo: str, product_id: uuid.UUID) -> list[dict]:
    report = _diagnosis()
    with Session(engine) as session:
        set_platform_db_context(session)
        achados = report.diagnose(session)
    return [
        achado for achado in achados
        if achado["tipo"] == tipo and achado["product_id"] == str(product_id)
    ]


def test_it_finds_a_loss_that_increased_the_balance():
    """A assinatura direta do defeito: `LOSS` com variação positiva."""
    report = _diagnosis()
    with Session(engine, expire_on_commit=False) as session:
        tenant_id, store_id, product_id = _store(session)
        session.add(InventoryMovement(
            tenant_id=tenant_id, store_id=store_id, product_id=product_id,
            actor_id=uuid.uuid4(), movement_type=MovementTypeEnum.LOSS,
            quantity=Decimal("5"), previous_balance=Decimal("10"),
            new_balance=Decimal("15"), reason="Perda que somou",
        ))
        session.add(InventoryBalance(
            tenant_id=tenant_id, store_id=store_id, product_id=product_id,
            quantity=Decimal("15"),
        ))
        session.commit()

    achados = _findings(report.SAIDA_POSITIVA, product_id)
    assert len(achados) == 1
    assert "+5.0000" in achados[0]["evidencia"]
    assert achados[0]["store_id"] == str(store_id)


def test_it_finds_a_line_whose_own_arithmetic_does_not_close():
    """`anterior + variação != posterior` não deveria existir em hipótese alguma."""
    report = _diagnosis()
    with Session(engine, expire_on_commit=False) as session:
        tenant_id, store_id, product_id = _store(session)
        session.add(InventoryMovement(
            tenant_id=tenant_id, store_id=store_id, product_id=product_id,
            actor_id=uuid.uuid4(), movement_type=MovementTypeEnum.PURCHASE,
            quantity=Decimal("2"), previous_balance=Decimal("10"),
            new_balance=Decimal("50"), reason="Linha impossível",
        ))
        session.commit()

    achados = _findings(report.ARITMETICA, product_id)
    assert len(achados) == 1
    assert "10.0000 + 2.0000 != 50.0000" in achados[0]["evidencia"]


def test_it_finds_a_balance_that_the_ledger_does_not_explain():
    """Saldo que não vem de movimento é escrita por fora do livro."""
    report = _diagnosis()
    with Session(engine, expire_on_commit=False) as session:
        tenant_id, store_id, product_id = _store(session)
        session.add(InventoryBalance(
            tenant_id=tenant_id, store_id=store_id, product_id=product_id,
            quantity=Decimal("7"),
        ))
        session.commit()

    achados = _findings(report.SALDO_DIVERGENTE, product_id)
    assert len(achados) == 1
    assert "diferença 7.0000" in achados[0]["evidencia"]


def test_a_consistent_product_produces_no_finding():
    """Sem falso positivo: livro e saldo coerentes não aparecem em lugar nenhum."""
    report = _diagnosis()
    with Session(engine, expire_on_commit=False) as session:
        tenant_id, store_id, product_id = _store(session)
        session.add(InventoryMovement(
            tenant_id=tenant_id, store_id=store_id, product_id=product_id,
            actor_id=uuid.uuid4(), movement_type=MovementTypeEnum.PURCHASE,
            quantity=Decimal("4"), previous_balance=Decimal("0"),
            new_balance=Decimal("4"), reason="Recebimento",
        ))
        session.add(InventoryMovement(
            tenant_id=tenant_id, store_id=store_id, product_id=product_id,
            actor_id=uuid.uuid4(), movement_type=MovementTypeEnum.LOSS,
            quantity=Decimal("-1"), previous_balance=Decimal("4"),
            new_balance=Decimal("3"), reason="Perda correta",
        ))
        session.add(InventoryBalance(
            tenant_id=tenant_id, store_id=store_id, product_id=product_id,
            quantity=Decimal("3"),
        ))
        session.commit()

    for tipo in (report.SAIDA_POSITIVA, report.ARITMETICA, report.SALDO_DIVERGENTE):
        assert _findings(tipo, product_id) == [], tipo


def test_the_diagnosis_leaves_the_rows_exactly_as_it_found_them():
    """Diagnóstico que escreve deixa de ser diagnóstico.

    Aqui não é varredura de fonte: as linhas são contadas e relidas depois da
    execução completa do levantamento sobre o banco inteiro.
    """
    report = _diagnosis()
    with Session(engine, expire_on_commit=False) as session:
        tenant_id, store_id, product_id = _store(session)
        session.add(InventoryMovement(
            tenant_id=tenant_id, store_id=store_id, product_id=product_id,
            actor_id=uuid.uuid4(), movement_type=MovementTypeEnum.LOSS,
            quantity=Decimal("5"), previous_balance=Decimal("10"),
            new_balance=Decimal("15"), reason="Perda que somou",
        ))
        session.commit()

    with Session(engine) as session:
        set_platform_db_context(session)
        antes = (
            len(session.exec(select(InventoryMovement)).all()),
            len(session.exec(select(InventoryBalance)).all()),
        )
        report.diagnose(session)
        depois = (
            len(session.exec(select(InventoryMovement)).all()),
            len(session.exec(select(InventoryBalance)).all()),
        )
        movimento = session.exec(select(InventoryMovement).where(
            InventoryMovement.product_id == product_id,
        )).one()

    assert antes == depois
    assert movimento.quantity == Decimal("5.0000"), (
        "o levantamento corrigiu a linha em vez de apenas apontá-la"
    )
    assert movimento.new_balance == Decimal("15.0000")
