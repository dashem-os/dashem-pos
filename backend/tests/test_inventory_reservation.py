"""O que está prometido a uma venda aberta não pode ser prometido de novo.

Em 07/09/2026 o banco publicado mostrava uma venda aberta com 18 unidades de um
produto cujo saldo era 16, e nenhum número do sistema sabia disso: o estoque só
se movia na conclusão, e entre adicionar o primeiro item e pagar não havia nada
segurando mercadoria. A falta aparecia como recusa no pagamento — depois de o
cliente já ter escolhido.

Estes testes fixam o contrato do ADR-032: reservar reduz o disponível na hora,
a recusa acontece na inclusão, cancelar devolve, concluir consome, e duas
estações concorrentes não prometem as mesmas unidades.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.catalog import (
    InventoryReservation, MovementTypeEnum, Product, ReservationSourceEnum,
    ReservationStatusEnum,
)
from app.models.identity import Store, Tenant, TenantStatusEnum
from app.services import inventory_service


def _session() -> Session:
    return Session(engine, expire_on_commit=False)


def _context(session: Session) -> TenantContext:
    suffix = uuid.uuid4().hex[:8]
    set_platform_db_context(session)
    tenant = Tenant(name=f"Reserva {suffix}", slug=f"reserva-{suffix}", status=TenantStatusEnum.ACTIVE)
    session.add(tenant)
    session.flush()
    store = Store(tenant_id=tenant.id, name="Matriz", code=f"RSV-{suffix}")
    session.add(store)
    session.commit()
    context = TenantContext(
        tenant_id=tenant.id, store_id=store.id, user_id=uuid.uuid4(),
        auth_subject=f"caixa-{suffix}",
    )
    set_tenant_db_context(session, context.tenant_id, context.store_id, context.user_id)
    return context


def _product(session: Session, context: TenantContext) -> uuid.UUID:
    suffix = uuid.uuid4().hex[:8]
    product = Product(
        tenant_id=context.tenant_id, name=f"Coca-Cola {suffix}", sku=f"RSV-{suffix}",
        tracks_inventory=True,
    )
    session.add(product)
    session.commit()
    return product.id


def _receive(session, context, product_id, quantity: str) -> None:
    inventory_service.adjust_stock(
        session=session, context=context, store_id=context.store_id,
        product_id=product_id, actor_id=context.user_id,
        movement_type=MovementTypeEnum.PURCHASE, quantity=Decimal(quantity),
        reason="Carga inicial",
    )
    session.commit()


def _reserve(session, context, product_id, quantity: str, *, sale_item_id=None, sale_id=None):
    return inventory_service.reserve_for_sale_item(
        session=session, context=context, store_id=context.store_id,
        product_id=product_id, quantity=Decimal(quantity),
        sale_id=sale_id or uuid.uuid4(), sale_item_id=sale_item_id or uuid.uuid4(),
        product_name="Coca-Cola",
    )


def test_reserving_reduces_what_can_still_be_promised():
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "16")

        assert inventory_service.available_to_promise(
            session, context, context.store_id, product_id) == Decimal("16.0000")

        _reserve(session, context, product_id, "10")
        session.commit()

        # O saldo físico não mudou: a mercadoria continua na prateleira.
        balance = inventory_service.get_balance(session, context, context.store_id, product_id)
        assert Decimal(str(balance.quantity)) == Decimal("16.0000")
        # O que mudou é o que ainda pode ser prometido.
        assert inventory_service.available_to_promise(
            session, context, context.store_id, product_id) == Decimal("6.0000")


def test_the_second_station_cannot_promise_what_the_first_already_did():
    """O cenário exato do relato: 16 na prateleira, 10 numa venda, 7 na outra."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "16")
        _reserve(session, context, product_id, "10")
        session.commit()

        with pytest.raises(HTTPException) as recusa:
            _reserve(session, context, product_id, "7")

    assert recusa.value.status_code == 409
    assert "6" in recusa.value.detail
    assert "vendas abertas" in recusa.value.detail


def test_releasing_gives_the_goods_back_immediately():
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "16")
        sale_id = uuid.uuid4()
        _reserve(session, context, product_id, "10", sale_id=sale_id)
        session.commit()

        inventory_service.release_reservations(session, context, sale_id=sale_id)
        session.commit()

        assert inventory_service.available_to_promise(
            session, context, context.store_id, product_id) == Decimal("16.0000")
        # E a outra estação passa a conseguir o que antes foi recusado.
        _reserve(session, context, product_id, "7")
        session.commit()
        assert inventory_service.available_to_promise(
            session, context, context.store_id, product_id) == Decimal("9.0000")


def test_consuming_does_not_give_the_goods_back():
    """Concluir não é liberar: a mercadoria saiu pela porta."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "16")
        sale_id = uuid.uuid4()
        _reserve(session, context, product_id, "10", sale_id=sale_id)
        session.commit()

        inventory_service.consume_reservations(session, context, sale_id=sale_id)
        inventory_service.adjust_stock(
            session=session, context=context, store_id=context.store_id,
            product_id=product_id, actor_id=context.user_id,
            movement_type=MovementTypeEnum.SALE, quantity=Decimal("10"),
            reason="Venda consumada",
        )
        session.commit()

        balance = inventory_service.get_balance(session, context, context.store_id, product_id)
        assert Decimal(str(balance.quantity)) == Decimal("6.0000")
        assert inventory_service.available_to_promise(
            session, context, context.store_id, product_id) == Decimal("6.0000")


def test_changing_the_quantity_does_not_compete_with_itself():
    """De 3 para 5, o que se compara com o disponível é o 5, não o 8."""
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "6")
        sale_item_id = uuid.uuid4()
        _reserve(session, context, product_id, "3", sale_item_id=sale_item_id)
        session.commit()

        _reserve(session, context, product_id, "5", sale_item_id=sale_item_id)
        session.commit()

        assert inventory_service.available_to_promise(
            session, context, context.store_id, product_id) == Decimal("1.0000")
        vivas = session.exec(select(InventoryReservation).where(
            InventoryReservation.sale_item_id == sale_item_id,
            InventoryReservation.status == ReservationStatusEnum.ACTIVE,
        )).all()
        assert len(vivas) == 1, "a mesma linha criou duas promessas"


def test_the_counter_cart_expires_and_the_tab_does_not():
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "20")

        carrinho = _reserve(session, context, product_id, "5")
        comanda = _reserve(session, context, product_id, "5")
        comanda.source_type = ReservationSourceEnum.TAB
        comanda.expires_at = None
        session.add(comanda)
        # Um carrinho abandonado meia hora atrás.
        carrinho.expires_at = carrinho.reserved_at.replace(year=carrinho.reserved_at.year - 1)
        session.add(carrinho)
        session.commit()

        assert inventory_service.expire_stale_reservations(session, context) == 1
        session.commit()

        session.refresh(carrinho)
        session.refresh(comanda)
        assert carrinho.status is ReservationStatusEnum.EXPIRED
        assert comanda.status is ReservationStatusEnum.ACTIVE, "mesa aberta não devolve estoque sozinha"
        # Rodar de novo não muda nada: a varredura é idempotente.
        assert inventory_service.expire_stale_reservations(session, context) == 0


def test_promising_more_than_exists_is_refused_before_the_payment():
    with _session() as session:
        context = _context(session)
        product_id = _product(session, context)
        _receive(session, context, product_id, "2")

        with pytest.raises(HTTPException) as recusa:
            _reserve(session, context, product_id, "3")

    assert recusa.value.status_code == 409
    assert "2" in recusa.value.detail


def test_the_refusal_is_written_the_way_a_person_would_say_it():
    """"Só há 0 disponível. 16 já está" saiu na tela em 07/09/2026."""
    from app.services.inventory_service import _recusa

    esgotado = _recusa("Coca-Cola Lata", Decimal("0"), Decimal("16"))
    assert esgotado == ("Não há mais 'Coca-Cola Lata' para vender agora: "
                        "16 unidades estão em vendas abertas.")
    sobrando = _recusa("Coca-Cola Lata", Decimal("6"), Decimal("10"))
    assert sobrando == ("Só há 6 disponíveis de 'Coca-Cola Lata': "
                        "10 unidades estão em vendas abertas.")
    uma = _recusa("Coca-Cola Lata", Decimal("1"), Decimal("1"))
    assert uma == "Só há 1 disponível de 'Coca-Cola Lata': 1 unidade está em vendas abertas."
    # Sem reserva nenhuma, a falta é da prateleira e não de outra venda.
    assert _recusa("Coca-Cola Lata", Decimal("0"), Decimal("0")) == (
        "Não há 'Coca-Cola Lata' em estoque nesta unidade.")


def test_two_simultaneous_inclusions_race_for_the_last_unit_and_only_one_wins():
    """A corrida construída, não torcida.

    A homologação de 09/09/2026 deixou isto como pendência específica: a
    travessia de duas estações é **sequencial** — espera a primeira pôr a
    unidade no carrinho antes de mandar a segunda tentar. Isso prova que uma
    reserva concluída impede a segunda inclusão; não prova que duas inclusões
    **simultâneas** se resolvem no banco.

    Uma prova que dispara as duas e torce pelo escalonador mede o escalonador.
    Esta constrói a corrida: a estação 1 abre transação, trava a linha do saldo
    e **segura**. A estação 2 dispara enquanto a trava está de pé, e a diferença
    aparece no relógio — ela só volta depois que a 1 solta.

    Sem o `FOR UPDATE` de `_lock_balance_row`, a estação 2 não esperaria nada:
    leria o mesmo disponível que a 1 leu e prometeria a mesma unidade.
    """
    import threading
    import time

    with _session() as preparo:
        context = _context(preparo)
        product_id = _product(preparo, context)
        _receive(preparo, context, product_id, "1")
        tenant_id, store_id, user_id = context.tenant_id, context.store_id, context.user_id

    def contexto_de(session: Session) -> TenantContext:
        ctx = TenantContext(tenant_id=tenant_id, store_id=store_id, user_id=user_id,
                            auth_subject="corrida")
        set_tenant_db_context(session, tenant_id, store_id, user_id)
        return ctx

    segurando = threading.Event()
    pode_soltar = threading.Event()
    resultado = {}

    def estacao_1():
        """Trava a linha do saldo e segura, como uma inclusão em andamento."""
        with _session() as session:
            ctx = contexto_de(session)
            inventory_service._lock_balance_row(session, ctx, store_id, product_id)
            segurando.set()
            pode_soltar.wait(timeout=30)
            # E então conclui a promessa da última unidade.
            _reserve(session, ctx, product_id, "1")
            session.commit()
            resultado["estacao_1"] = "reservou"

    primeira = threading.Thread(target=estacao_1)
    primeira.start()
    assert segurando.wait(timeout=30), "a estação 1 não chegou a travar a linha"

    # A estação 2 dispara **com a trava de pé**. Ela não pode passar por cima.
    def estacao_2():
        comeco = time.perf_counter()
        with _session() as session:
            ctx = contexto_de(session)
            try:
                _reserve(session, ctx, product_id, "1")
                session.commit()
                resultado["estacao_2"] = "reservou"
            except HTTPException as recusa:
                session.rollback()
                resultado["estacao_2"] = "recusada"
                resultado["motivo"] = str(recusa.detail)
        resultado["espera_ms"] = (time.perf_counter() - comeco) * 1000

    segunda = threading.Thread(target=estacao_2)
    segunda.start()

    # Meio segundo de trava de pé: se a estação 2 já tivesse terminado aqui, ela
    # não teria esperado por nada, e a prova não valeria.
    time.sleep(0.5)
    assert "estacao_2" not in resultado, (
        "a estação 2 concluiu com a linha travada: a inclusão não serializa no banco"
    )

    pode_soltar.set()
    primeira.join(timeout=30)
    segunda.join(timeout=30)

    assert resultado.get("estacao_1") == "reservou"
    assert resultado.get("estacao_2") == "recusada", resultado
    # O relógio é a prova de que houve espera, e não sorte de escalonamento.
    assert resultado["espera_ms"] > 400, resultado
    assert "vendas abertas" in resultado.get("motivo", ""), resultado

    # E o servidor, ao fim: uma promessa só, e a prateleira não ficou negativa.
    with _session() as conferencia:
        ctx = contexto_de(conferencia)
        reservas = conferencia.exec(select(InventoryReservation).where(
            InventoryReservation.tenant_id == tenant_id,
            InventoryReservation.product_id == product_id,
            InventoryReservation.status == ReservationStatusEnum.ACTIVE,
        )).all()
        assert len(reservas) == 1, reservas
        assert sum(Decimal(str(r.quantity)) for r in reservas) == Decimal("1.0000")
        assert inventory_service.available_to_promise(
            conferencia, ctx, store_id, product_id) == Decimal("0.0000")
        saldo = inventory_service.get_balance(conferencia, ctx, store_id, product_id)
        assert Decimal(str(saldo.quantity)) == Decimal("1.0000"), "a prateleira não muda ao reservar"
