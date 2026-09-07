"""Contar a prateleira sem apagar a venda que entrou no meio.

A operação cotidiana informa **o total encontrado** e deixa o servidor calcular a
diferença. Isso só é seguro se ela souber que o saldo não mudou entre a leitura
da prateleira e a confirmação: aceitar uma contagem feita sobre um saldo velho
apagaria do estoque a venda que aconteceu enquanto alguém contava.

O que estes testes fixam, um por exigência:

* **versão movida por toda movimentação** — venda, entrada, perda, devolução e
  ajuste. Uma versão que só algumas operações movem é proteção com buraco;
* **conferência e gravação atômicas** — a linha do saldo fica bloqueada entre
  verificar a versão e escrever, sem espaço para uma venda no meio;
* **contagem zero é contagem** — prateleira vazia é achado, e é diferente de não
  preencher o campo;
* **contagem igual ao saldo** registra a conferência sem inventar movimento;
* **conflito compreensível** — a recusa devolve o estado atual para a tela poder
  preservar o que foi digitado e pedir nova conferência, nunca aceitar em
  silêncio com a versão nova;
* **reenvio não duplica** a diferença;
* **`ADJUSTMENT` restrito de verdade**, pelo motor de permissão e não pela prosa.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app.api.v1.endpoints.inventory import (
    StockAdjustDTO, StockCountDTO, adjust_stock_endpoint, count_stock_endpoint,
)
from app.core.context import TenantContext, authorize_tenant_context
from app.core.database import engine
from app.core.permissions import route_requirement
from app.core.security import AuthPrincipal
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.catalog import (
    InventoryBalance, InventoryCount, InventoryMovement, MovementTypeEnum, Product,
)
from app.models.identity import (
    AuthIdentity, Membership, MembershipStatusEnum, RoleEnum, Store, Tenant,
    TenantStatusEnum, User,
)
from app.models.platform import EntitlementStatusEnum, TenantCapability
from app.services import inventory_service


def _session() -> Session:
    return Session(engine, expire_on_commit=False)


def _context(session: Session) -> TenantContext:
    suffix = uuid.uuid4().hex[:8]
    set_platform_db_context(session)
    tenant = Tenant(
        name=f"Contagem {suffix}", slug=f"contagem-{suffix}", status=TenantStatusEnum.ACTIVE,
    )
    session.add(tenant)
    session.flush()
    store = Store(tenant_id=tenant.id, name="Matriz", code=f"CNT-{suffix}")
    session.add(store)
    session.commit()
    context = TenantContext(
        tenant_id=tenant.id, store_id=store.id, user_id=uuid.uuid4(),
        auth_subject=f"conferente-{suffix}",
    )
    set_tenant_db_context(session, context.tenant_id, context.store_id, context.user_id)
    return context


def _product(session: Session, context: TenantContext, *, tracks: bool = True) -> uuid.UUID:
    suffix = uuid.uuid4().hex[:8]
    product = Product(
        tenant_id=context.tenant_id, name=f"Mercadoria {suffix}", sku=f"CNT-{suffix}",
        tracks_inventory=tracks,
    )
    session.add(product)
    session.commit()
    return product.id


def _receive(session, context, product_id, quantity: str) -> None:
    inventory_service.adjust_stock(
        session=session, context=context, store_id=context.store_id,
        product_id=product_id, actor_id=context.user_id,
        movement_type=MovementTypeEnum.PURCHASE, quantity=Decimal(quantity),
        reason="Recebimento",
    )
    session.commit()


def _balance(context: TenantContext, product_id) -> InventoryBalance | None:
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, None)
        return session.exec(select(InventoryBalance).where(
            InventoryBalance.product_id == product_id,
        )).first()


def _counts(context: TenantContext, product_id) -> list[InventoryCount]:
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, None)
        return session.exec(select(InventoryCount).where(
            InventoryCount.product_id == product_id,
        )).all()


def _movements(context: TenantContext, product_id) -> list[InventoryMovement]:
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, None)
        return session.exec(select(InventoryMovement).where(
            InventoryMovement.product_id == product_id,
        )).all()


# ------------------------------------------------------------------- a versão

@pytest.mark.parametrize("movement_type", [
    MovementTypeEnum.PURCHASE, MovementTypeEnum.LOSS,
    MovementTypeEnum.RETURN, MovementTypeEnum.SALE, MovementTypeEnum.ADJUSTMENT,
])
def test_every_kind_of_movement_moves_the_version(movement_type):
    """Uma versão que só algumas operações movem é uma proteção com buraco."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "10")
        antes = _balance(context, product_id).version

        quantity = Decimal("-1") if movement_type is MovementTypeEnum.ADJUSTMENT else Decimal("1")
        inventory_service.adjust_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            movement_type=movement_type, quantity=quantity, reason="Movimento",
        )
        session.commit()

    assert _balance(context, product_id).version == antes + 1, movement_type


def test_the_first_movement_starts_the_version_at_one():
    """Produto sem linha de saldo tem versão 0; o primeiro movimento a cria."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        assert _balance(context, product_id) is None

        _receive(session, context, product_id, "4")

    assert _balance(context, product_id).version == 1


# ----------------------------------------------------------------- a contagem

def test_counting_more_than_the_balance_records_the_difference():
    """Encontrou 12 onde havia 10: entram 2, e o movimento explica de onde."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "10")
        version = _balance(context, product_id).version

        record, balance, movement = inventory_service.count_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            counted_quantity=Decimal("12"), expected_version=version,
            idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
        )
        session.commit()

    assert record.difference == Decimal("2.0000")
    assert Decimal(str(balance.quantity)) == Decimal("12.0000")
    assert movement is not None and movement.movement_type is MovementTypeEnum.ADJUSTMENT
    assert movement.quantity == Decimal("2.0000")


def test_counting_zero_is_a_count_and_empties_the_shelf():
    """Prateleira vazia é achado, não campo em branco."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "7")
        version = _balance(context, product_id).version

        record, balance, movement = inventory_service.count_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            counted_quantity=Decimal("0"), expected_version=version,
            idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
        )
        session.commit()

    assert record.counted_quantity == Decimal("0.0000")
    assert record.difference == Decimal("-7.0000")
    assert Decimal(str(balance.quantity)) == Decimal("0.0000")
    assert movement is not None


def test_counting_exactly_the_balance_records_the_check_and_invents_nothing():
    """Conferir e bater é informação: alguém olhou a prateleira naquele dia."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "5")
        version = _balance(context, product_id).version

        record, balance, movement = inventory_service.count_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            counted_quantity=Decimal("5"), expected_version=version,
            idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
        )
        session.commit()

    assert movement is None, "a conferência inventou um movimento"
    assert record.difference == Decimal("0.0000")
    assert record.movement_id is None
    assert len(_counts(context, product_id)) == 1, "a conferência não foi registrada"
    # Um movimento só: o recebimento. A contagem não acrescentou nenhum.
    assert len(_movements(context, product_id)) == 1
    assert _balance(context, product_id).version == version, (
        "conferência sem diferença mexeu na versão de quem não movimentou nada"
    )


def test_counting_a_product_with_no_balance_row_starts_from_version_zero():
    """Nunca movimentado é versão 0, e a contagem cria o saldo."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)

        record, balance, _ = inventory_service.count_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            counted_quantity=Decimal("3"), expected_version=0,
            idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
        )
        session.commit()

    assert record.previous_balance == Decimal("0.0000")
    assert Decimal(str(balance.quantity)) == Decimal("3.0000")


# ------------------------------------------------------------------ o conflito

def test_a_sale_during_the_count_is_never_erased_by_it():
    """A venda entrou no meio: a contagem é recusada, não aplicada por cima."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "10")
        version_lida = _balance(context, product_id).version

        # Enquanto a pessoa conta, o balcão vende duas unidades.
        inventory_service.adjust_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            movement_type=MovementTypeEnum.SALE, quantity=Decimal("2"),
            reason="Venda durante a contagem",
        )
        session.commit()

        with pytest.raises(HTTPException) as conflito:
            inventory_service.count_stock(
                session=session, context=context, store_id=context.store_id,
                product_id=product_id, actor_id=context.user_id,
                counted_quantity=Decimal("10"), expected_version=version_lida,
                idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
            )
        session.rollback()

    assert conflito.value.status_code == 409
    detalhe = conflito.value.detail
    # A recusa precisa dar à tela o que ela mostra: o que mudou e o que fazer.
    assert "novamente" in detalhe["message"]
    assert detalhe["expected_version"] == version_lida
    assert detalhe["current_version"] == version_lida + 1
    assert detalhe["current_quantity"] == "8.0000"

    assert Decimal(str(_balance(context, product_id).quantity)) == Decimal("8.0000"), (
        "a contagem sobre saldo velho apagou a venda do estoque"
    )
    assert _counts(context, product_id) == [], "conflito registrou conferência"


def test_a_refused_count_leaves_no_trace_at_all():
    """Recusa não é meia-gravação: nem conferência, nem movimento, nem versão."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "6")
        version = _balance(context, product_id).version

        with pytest.raises(HTTPException):
            inventory_service.count_stock(
                session=session, context=context, store_id=context.store_id,
                product_id=product_id, actor_id=context.user_id,
                counted_quantity=Decimal("6"), expected_version=version + 5,
                idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
            )
        session.rollback()

    assert _balance(context, product_id).version == version
    assert _counts(context, product_id) == []
    assert len(_movements(context, product_id)) == 1


# ------------------------------------------------------------------- reenvio

def test_resending_the_same_confirmation_records_one_difference():
    """Repetir a confirmação devolve a mesma contagem, sem segunda diferença."""
    key = f"count-{uuid.uuid4().hex[:10]}"
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "10")
        version = _balance(context, product_id).version

        primeira, _, _ = inventory_service.count_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            counted_quantity=Decimal("8"), expected_version=version,
            idempotency_key=key,
        )
        session.commit()
        segunda, balance, _ = inventory_service.count_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            counted_quantity=Decimal("8"), expected_version=version,
            idempotency_key=key,
        )
        session.commit()

    assert primeira.id == segunda.id
    assert Decimal(str(balance.quantity)) == Decimal("8.0000"), "a diferença foi aplicada duas vezes"
    assert len(_counts(context, product_id)) == 1
    assert len(_movements(context, product_id)) == 2  # recebimento + um ajuste


def test_a_negative_count_is_refused():
    """Não se encontra menos que nada numa prateleira."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "5")
        version = _balance(context, product_id).version

        with pytest.raises(HTTPException) as refused:
            inventory_service.count_stock(
                session=session, context=context, store_id=context.store_id,
                product_id=product_id, actor_id=context.user_id,
                counted_quantity=Decimal("-1"), expected_version=version,
                idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
            )
        session.rollback()

    assert refused.value.status_code == 400


def test_an_item_without_stock_control_cannot_be_counted():
    """Serviço não tem prateleira."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context, tracks=False)

        with pytest.raises(HTTPException) as refused:
            inventory_service.count_stock(
                session=session, context=context, store_id=context.store_id,
                product_id=product_id, actor_id=context.user_id,
                counted_quantity=Decimal("3"), expected_version=0,
                idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
            )
        session.rollback()

    assert refused.value.status_code == 400


# ------------------------------------------------ o ajuste técnico é restrito

def test_the_technical_adjustment_has_its_own_permission():
    """A restrição vive no motor de permissão, não na documentação."""
    assert route_requirement("POST", "/api/v1/inventory/adjust").permission == "inventory.adjust"
    assert route_requirement("POST", "/api/v1/inventory/count").permission == "inventory.count"
    assert route_requirement(
        "POST", "/api/v1/inventory/technical-adjustment",
    ).permission == "inventory.adjust.technical"


def test_the_common_route_refuses_a_signed_adjustment():
    """`ADJUSTMENT` saiu da rota que qualquer movimentador alcança."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "10")

        with pytest.raises(HTTPException) as refused:
            adjust_stock_endpoint(
                data=StockAdjustDTO(
                    store_id=context.store_id, product_id=product_id,
                    actor_id=context.user_id, movement_type=MovementTypeEnum.ADJUSTMENT,
                    quantity=-2.0, reason="Diferença à mão",
                ),
                context=context, x_idempotency_key=None, x_correlation_id=None,
                session=session,
            )
        session.rollback()

    assert refused.value.status_code == 400
    assert "contando a prateleira" in refused.value.detail


def _with_role(role: RoleEnum) -> tuple[uuid.UUID, uuid.UUID, AuthPrincipal]:
    suffix = uuid.uuid4().hex[:8]
    subject = str(uuid.uuid4())
    with _session() as session:
        set_platform_db_context(session)
        tenant = Tenant(
            name=f"Autoridade {suffix}", slug=f"autoridade-{suffix}",
            status=TenantStatusEnum.ACTIVE,
        )
        session.add(tenant)
        session.flush()
        store = Store(tenant_id=tenant.id, name="Matriz", code=f"AUT-{suffix}")
        session.add(store)
        user = User(email=f"{role.value.lower()}-{suffix}@example.test", full_name="Pessoa")
        session.add(user)
        session.flush()
        session.add(AuthIdentity(
            user_id=user.id, provider="supabase", provider_subject=subject,
        ))
        session.add(Membership(
            user_id=user.id, tenant_id=tenant.id, store_id=None,
            role=role, status=MembershipStatusEnum.ACTIVE,
        ))
        for key in ("catalog", "inventory", "payments"):
            session.add(TenantCapability(
                tenant_id=tenant.id, key=key, enabled=True,
                status=EntitlementStatusEnum.ACTIVE,
            ))
        session.commit()
        principal = AuthPrincipal(
            subject=subject, email=user.email, session_id=str(uuid.uuid4()),
            assurance_level="aal1", claims={"sub": subject},
        )
        return tenant.id, store.id, principal


def test_a_manager_counts_the_shelf_but_does_not_hand_write_a_difference():
    """A separação medida pelo caminho autenticado, não pela intenção do texto."""
    tenant_id, store_id, principal = _with_role(RoleEnum.MANAGER)

    with Session(engine) as session:
        set_platform_db_context(session)
        contagem = authorize_tenant_context(
            session, principal, tenant_id, store_id, "POST", "/api/v1/inventory/count",
        )
        assert "inventory.count" in contagem.permissions

        with pytest.raises(HTTPException) as refused:
            authorize_tenant_context(
                session, principal, tenant_id, store_id,
                "POST", "/api/v1/inventory/technical-adjustment",
            )
    assert refused.value.status_code == 403


def test_an_admin_may_hand_write_the_difference():
    """Alguém precisa poder corrigir o que a contagem não resolve."""
    tenant_id, store_id, principal = _with_role(RoleEnum.ADMIN)

    with Session(engine) as session:
        set_platform_db_context(session)
        tecnico = authorize_tenant_context(
            session, principal, tenant_id, store_id,
            "POST", "/api/v1/inventory/technical-adjustment",
        )
    assert "inventory.adjust.technical" in tecnico.permissions


def test_a_cashier_reaches_neither():
    """Quem opera o caixa consulta estoque e não o movimenta."""
    tenant_id, store_id, principal = _with_role(RoleEnum.CASHIER)

    for path in ("/api/v1/inventory/count", "/api/v1/inventory/technical-adjustment"):
        with Session(engine) as session:
            set_platform_db_context(session)
            with pytest.raises(HTTPException) as refused:
                authorize_tenant_context(
                    session, principal, tenant_id, store_id, "POST", path,
                )
        assert refused.value.status_code == 403, path


def test_the_route_writes_the_count_and_the_balance_together():
    """Pela rota, com a transação confirmada por quem coordena a operação."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "10")
        version = _balance(context, product_id).version

        response = count_stock_endpoint(
            data=StockCountDTO(
                store_id=context.store_id, product_id=product_id,
                actor_id=context.user_id, counted_quantity=Decimal("9"),
                expected_version=version, reason="Conferência do fim do dia",
            ),
            context=context, idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
            x_correlation_id=None, session=session,
        )

    assert Decimal(str(response["balance"].quantity)) == Decimal("9.0000")
    assert response["count"].difference == Decimal("-1.0000")
    assert Decimal(str(_balance(context, product_id).quantity)) == Decimal("9.0000")


# --------------------------------------------------- conferir e gravar, junto

def test_a_sale_cannot_slip_between_checking_the_version_and_writing_the_count():
    """A linha do saldo fica bloqueada enquanto a contagem não confirma.

    Verificar a versão e escrever o resultado no mesmo bloco de código não basta:
    se outra transação puder tocar a linha entre os dois passos, a proteção é só
    aparente. O que fecha a passagem é o bloqueio da linha, mantido até o fim da
    transação da contagem.

    A sessão A entra na contagem e **não confirma**. A sessão B tenta vender a
    mesma mercadoria com `lock_timeout` curto: se a linha estivesse livre, ela
    passaria; como está bloqueada, espera e estoura o tempo.

    O que este teste prova é isto e só isto: **uma linha de saldo que já existe
    fica bloqueada neste cenário.** Ele não prova ausência de janela em geral —
    o produto que ainda não tem linha de saldo é caso à parte, coberto pelo
    teste do primeiro saldo, porque `FOR UPDATE` não bloqueia linha inexistente.
    """
    with _session() as a:
        context = _context(a)
        product_id = _product(a, context)
        _receive(a, context, product_id, "10")
        version = _balance(context, product_id).version

        # A conta 8 e segura a linha: a transação continua aberta.
        inventory_service.count_stock(
            session=a, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            counted_quantity=Decimal("8"), expected_version=version,
            idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
        )

        with Session(engine) as b:
            set_tenant_db_context(b, context.tenant_id, context.store_id, context.user_id)
            b.exec(text("SET lock_timeout = '750ms'"))
            with pytest.raises(DBAPIError) as bloqueada:
                inventory_service.adjust_stock(
                    session=b, context=context, store_id=context.store_id,
                    product_id=product_id, actor_id=context.user_id,
                    movement_type=MovementTypeEnum.SALE, quantity=Decimal("1"),
                    reason="Venda tentando entrar no meio da contagem",
                )
            b.rollback()
        assert "lock" in str(bloqueada.value).lower()

        a.commit()

    # A contagem valeu; a venda não entrou no meio dela.
    assert Decimal(str(_balance(context, product_id).quantity)) == Decimal("8.0000")
    assert _balance(context, product_id).version == version + 1


def test_after_the_count_commits_the_sale_lands_on_top_of_it():
    """Bloquear não é recusar: quem esperou passa, e passa depois."""
    with _session() as a:
        context = _context(a)
        product_id = _product(a, context)
        _receive(a, context, product_id, "10")
        version = _balance(context, product_id).version

        inventory_service.count_stock(
            session=a, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            counted_quantity=Decimal("8"), expected_version=version,
            idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
        )
        a.commit()

        with _session() as b:
            set_tenant_db_context(b, context.tenant_id, context.store_id, context.user_id)
            inventory_service.adjust_stock(
                session=b, context=context, store_id=context.store_id,
                product_id=product_id, actor_id=context.user_id,
                movement_type=MovementTypeEnum.SALE, quantity=Decimal("1"),
                reason="Venda depois da contagem",
            )
            b.commit()

    assert Decimal(str(_balance(context, product_id).quantity)) == Decimal("7.0000")
    assert _balance(context, product_id).version == version + 2


# ---------------------------------------------------------- o primeiro saldo

def test_a_first_receipt_cannot_slip_past_a_count_on_a_product_with_no_balance_row():
    """`FOR UPDATE` não bloqueia linha que não existe — então a linha é criada.

    Produto nunca movimentado não tem linha de saldo. Sem nada a bloquear, uma
    contagem e um primeiro recebimento simultâneos passariam os dois, e o
    segundo escreveria por cima do primeiro sem que a versão acusasse.

    A contagem materializa a linha com saldo e versão zero antes de travá-la.
    Aqui a sessão A conta e não confirma; a sessão B tenta o primeiro
    recebimento e espera, estourando o `lock_timeout`.
    """
    with _session() as a:
        context = _context(a)
        product_id = _product(a, context)
        assert _balance(context, product_id) is None, "o produto já tinha saldo"

        inventory_service.count_stock(
            session=a, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            counted_quantity=Decimal("4"), expected_version=0,
            idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
        )

        with Session(engine) as b:
            set_tenant_db_context(b, context.tenant_id, context.store_id, context.user_id)
            b.exec(text("SET lock_timeout = '750ms'"))
            with pytest.raises(DBAPIError) as bloqueada:
                inventory_service.adjust_stock(
                    session=b, context=context, store_id=context.store_id,
                    product_id=product_id, actor_id=context.user_id,
                    movement_type=MovementTypeEnum.PURCHASE, quantity=Decimal("10"),
                    reason="Primeiro recebimento durante a contagem",
                )
            b.rollback()
        assert "lock" in str(bloqueada.value).lower()
        a.commit()

    assert Decimal(str(_balance(context, product_id).quantity)) == Decimal("4.0000")


def test_a_first_receipt_before_the_count_makes_the_count_conflict():
    """Quem chegou primeiro moveu a versão, e a contagem sobre zero é recusada."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "10")

        with pytest.raises(HTTPException) as conflito:
            inventory_service.count_stock(
                session=session, context=context, store_id=context.store_id,
                product_id=product_id, actor_id=context.user_id,
                counted_quantity=Decimal("3"), expected_version=0,
                idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
            )
        session.rollback()

    assert conflito.value.status_code == 409
    assert conflito.value.detail["current_version"] == 1
    assert Decimal(str(_balance(context, product_id).quantity)) == Decimal("10.0000")


def test_materialising_the_row_does_not_invent_stock():
    """A linha criada para poder ser travada nasce em zero, e zero é verdade."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)

        inventory_service.count_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            counted_quantity=Decimal("0"), expected_version=0,
            idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
        )
        session.commit()

    saldo = _balance(context, product_id)
    assert Decimal(str(saldo.quantity)) == Decimal("0.0000")
    # Contar zero onde havia zero é conferência, não movimento.
    assert _movements(context, product_id) == []
    assert len(_counts(context, product_id)) == 1


# ------------------------------------------- reenvio contra reaproveitamento

@pytest.mark.parametrize("campo", ["quantidade", "versão", "produto"])
def test_the_same_key_with_different_content_is_refused(campo):
    """Reenviar é repetir o mesmo comando; trocar o conteúdo é outro comando.

    Devolver o resultado antigo para um comando diferente confirmaria uma
    contagem que ninguém fez. A unicidade da chave não distingue os dois casos.
    """
    key = f"count-{uuid.uuid4().hex[:10]}"
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        outro_id = _product(session, context)
        _receive(session, context, product_id, "10")
        _receive(session, context, outro_id, "10")
        version = _balance(context, product_id).version

        inventory_service.count_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            counted_quantity=Decimal("8"), expected_version=version,
            idempotency_key=key,
        )
        session.commit()

        alterado = {
            "quantidade": {"counted_quantity": Decimal("9")},
            "versão": {"expected_version": version + 1},
            "produto": {"product_id": outro_id},
        }[campo]
        pedido = {
            "product_id": product_id, "counted_quantity": Decimal("8"),
            "expected_version": version, **alterado,
        }
        with pytest.raises(HTTPException) as refused:
            inventory_service.count_stock(
                session=session, context=context, store_id=context.store_id,
                actor_id=context.user_id, idempotency_key=key, **pedido,
            )
        session.rollback()

    assert refused.value.status_code == 409
    assert "outro comando" in refused.value.detail
    # E o saldo continua o da contagem original, sem segunda diferença.
    assert Decimal(str(_balance(context, product_id).quantity)) == Decimal("8.0000")
    assert len(_counts(context, product_id)) == 1


# ------------------------------------------------------------------ precisão

def test_a_quantity_beyond_the_stored_precision_is_refused_not_rounded():
    """Arredondar em silêncio perde mercadoria sem ninguém ficar sabendo."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)

        with pytest.raises(HTTPException) as refused:
            inventory_service.adjust_stock(
                session=session, context=context, store_id=context.store_id,
                product_id=product_id, actor_id=context.user_id,
                movement_type=MovementTypeEnum.PURCHASE, quantity=Decimal("1.00005"),
                reason="Precisão além da coluna",
            )
        session.rollback()

    assert refused.value.status_code == 400
    assert "quatro casas" in refused.value.detail


def test_a_count_beyond_the_stored_precision_is_refused_too():
    """A mesma régua na contagem: o que ela informa vira saldo."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "10")
        version = _balance(context, product_id).version

        with pytest.raises(HTTPException) as refused:
            inventory_service.count_stock(
                session=session, context=context, store_id=context.store_id,
                product_id=product_id, actor_id=context.user_id,
                counted_quantity=Decimal("9.99999"), expected_version=version,
                idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
            )
        session.rollback()

    assert refused.value.status_code == 400
    assert "quantidade contada" in refused.value.detail


def test_count_difference_and_movement_share_the_same_precision():
    """Contado, diferença e movimento têm de bater até a última casa."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "10.1234")
        version = _balance(context, product_id).version

        record, balance, movement = inventory_service.count_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            counted_quantity=Decimal("9.8765"), expected_version=version,
            idempotency_key=f"count-{uuid.uuid4().hex[:10]}",
        )
        session.commit()

    assert record.counted_quantity == Decimal("9.8765")
    assert record.previous_balance == Decimal("10.1234")
    assert record.difference == Decimal("-0.2469")
    assert movement.quantity == Decimal("-0.2469")
    assert movement.previous_balance + movement.quantity == movement.new_balance
    assert Decimal(str(balance.quantity)) == Decimal("9.8765")
