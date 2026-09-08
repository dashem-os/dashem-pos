import uuid
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Union
from sqlalchemy import func
from sqlmodel import Session, select, text
from fastapi import HTTPException, status
from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.catalog import (
    InventoryBalance, InventoryCount, InventoryMovement, InventoryReservation,
    MovementOriginEnum, MovementTypeEnum, Product, ReservationSourceEnum,
    ReservationStatusEnum,
)
from app.services import reliability_service

# Cada tipo de movimento tem uma direção, e é ela que decide o efeito no saldo.
# Antes o serviço somava a quantidade recebida qualquer que fosse o tipo, e quem
# informava o sinal era quem chamava — de modo que registrar perda de 5 unidades
# acrescentava 5 ao estoque, com o movimento gravado dizendo `LOSS · 5` numa
# linha em que o saldo subiu. O livro mentia junto com o saldo.
INCOMING_MOVEMENTS = frozenset({MovementTypeEnum.PURCHASE, MovementTypeEnum.RETURN})
OUTGOING_MOVEMENTS = frozenset({MovementTypeEnum.SALE, MovementTypeEnum.LOSS})


# A coluna é `Numeric(14,4)`. Aceitar mais casas e deixar o banco arredondar
# perderia mercadoria em silêncio — e o silêncio é o problema, não a quarta casa.
QUANTITY_PLACES = Decimal("0.0001")
QUANTITY_CEILING = Decimal("10000000000")  # Numeric(14,4): dez dígitos inteiros


def exact_quantity(value: Union[float, Decimal], field: str = "quantidade") -> Decimal:
    """A quantidade como ela será gravada, ou uma recusa dizendo por quê.

    O arredondamento que o banco faria é invisível: 0.00005 vira 0.0001 e
    ninguém fica sabendo. Aqui a perda é recusada em vez de aplicada.
    """
    quantity = Decimal(str(value))
    if not quantity.is_finite():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A {field} precisa ser um número finito.",
        )
    # `Numeric(14,4)` guarda dez dígitos inteiros. Acima disso o `quantize`
    # estoura com `InvalidOperation`, que viraria 500 — erro do servidor por um
    # número que a pessoa digitou. É recusa, e recusa é 400.
    if abs(quantity) >= QUANTITY_CEILING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"A {field} excede o máximo que o estoque registra "
                f"({QUANTITY_CEILING - 1} unidades)."
            ),
        )
    try:
        exata = quantity.quantize(QUANTITY_PLACES, rounding=ROUND_DOWN)
    except InvalidOperation:  # pragma: no cover - o teto acima já barra
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A {field} não pode ser registrada com esta precisão.",
        )
    if quantity != exata:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"A {field} tem mais de quatro casas decimais e seria arredondada. "
                f"Informe até 0,0001."
            ),
        )
    return quantity.quantize(QUANTITY_PLACES)


def _absent_balance(tenant_id, store_id, product_id) -> InventoryBalance:
    """O saldo de quem nunca foi movimentado: zero, e **versão zero**.

    A versão padrão do modelo é 1, que é o que a primeira linha real recebe. Mas
    esta instância não é uma linha: ela representa a ausência de uma, e a
    contagem trata ausência como versão 0. Devolver 1 aqui fazia a tela mandar
    uma expectativa que o servidor nunca podia satisfazer — a primeira contagem
    de um produto novo entrava em conflito para sempre, porque a recusa desfaz a
    linha materializada e a leitura seguinte devolvia 1 de novo.
    """
    return InventoryBalance(
        tenant_id=tenant_id, store_id=store_id, product_id=product_id,
        quantity=Decimal("0.00"), version=0,
    )


def _amount(value: Decimal) -> str:
    """Quantidade como uma pessoa escreve: sem zeros à direita inventados."""
    normalized = value.normalize()
    return f"{normalized:f}"


def signed_variation(
    movement_type: MovementTypeEnum, quantity: Union[float, Decimal],
) -> Decimal:
    """A variação assinada que esta operação aplica ao saldo.

    `ADJUSTMENT` é a única operação que carrega o próprio sinal: ela *é* a
    diferença apurada, e é a operação técnica restrita. Todas as outras recebem
    magnitude e têm a direção decidida aqui.

    Quantidade assinada numa operação direcional é recusada em vez de invertida.
    Inverter em silêncio manteria a ambiguidade — não há como saber se quem
    mandou `-3` numa perda estava dizendo o efeito ou a magnitude — e ainda
    esconderia o cliente que precisa ser corrigido.
    """
    variation = exact_quantity(quantity)
    if variation == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quantidade zero não movimenta estoque e não gera movimento.",
        )
    if movement_type in INCOMING_MOVEMENTS or movement_type in OUTGOING_MOVEMENTS:
        if variation < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Informe a quantidade positiva: a operação é que define "
                    "entrada ou saída de estoque."
                ),
            )
        return variation if movement_type in INCOMING_MOVEMENTS else -variation
    return variation


def adjust_stock(
    session: Session,
    context: TenantContext,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    actor_id: uuid.UUID,
    movement_type: MovementTypeEnum,
    quantity: Union[float, Decimal],
    reason: Optional[str] = None,
    correlation_id: Optional[str] = None,
    sale_item_id: Optional[uuid.UUID] = None,
    origin: Optional[MovementOriginEnum] = None,
) -> Tuple[Optional[InventoryMovement], InventoryBalance, bool]:
    actor_id = resolve_actor(context, actor_id)
    qty_dec = signed_variation(movement_type, quantity)

    if context.store_id and store_id != context.store_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Movimentação fora da unidade ativa.")

    # 1. Verify Product exists and belongs to tenant
    product_query = select(Product).where(Product.id == product_id)
    product_query = scope_tenant_query(product_query, Product, context)
    product = session.exec(product_query).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product '{product_id}' not found for this tenant."
        )

    # 2. Check invariant: If item does NOT track inventory (e.g. Service), bypass movement
    if not product.tracks_inventory:
        balance_query = select(InventoryBalance).where(
            InventoryBalance.store_id == store_id,
            InventoryBalance.product_id == product_id
        )
        balance_query = scope_tenant_query(balance_query, InventoryBalance, context)
        balance = session.exec(balance_query).first()
        if not balance:
            balance = _absent_balance(context.tenant_id, store_id, product_id)
        return None, balance, False

    # 3. ATOMIC POSTGRESQL UPSERT: Handles first-balance creation & concurrent updates with zero race conditions
    now = datetime.utcnow()
    # A versão sobe aqui, junto com o saldo e na mesma instrução: qualquer
    # movimento — venda, entrada, perda, devolução, ajuste — invalida a
    # expectativa de quem estava contando. Separar as duas escritas abriria
    # exatamente a janela que a contagem precisa fechar.
    upsert_query = text("""
        INSERT INTO inventory_balances (id, tenant_id, store_id, product_id, quantity, minimum_stock, version, updated_at)
        VALUES (:id, :tenant_id, :store_id, :product_id, :quantity, 0.0, 1, :now)
        ON CONFLICT (tenant_id, store_id, product_id) DO UPDATE
        SET quantity = inventory_balances.quantity + EXCLUDED.quantity,
            version = inventory_balances.version + 1,
            updated_at = :now
        RETURNING inventory_balances.quantity AS new_balance,
                  inventory_balances.version AS new_version;
    """)

    result = session.exec(upsert_query, params={
        "id": str(uuid.uuid4()),
        "tenant_id": str(context.tenant_id),
        "store_id": str(store_id),
        "product_id": str(product_id),
        # `Decimal`, não `float`. A linha acima monta `qty_dec` justamente para
        # não perder precisão, e converter aqui jogaria esse cuidado fora na
        # borda do banco — a coluna é `Numeric(14,4)` e psycopg2 adapta Decimal
        # nativamente. É o único float deste repositório que **escreve** saldo;
        # os demais são serialização de projeção.
        "quantity": qty_dec,
        "now": now
    }).first()

    new_balance = Decimal(str(result[0]))
    previous_balance = new_balance - qty_dec

    # Não existe saldo negativo: uma saída maior que o disponível é recusada, seja
    # ela venda, perda ou diferença apurada. Antes só a venda era barrada, o que
    # deixava a perda cavar saldo negativo por um caminho paralelo.
    if new_balance < Decimal("0.00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            # Sem código interno: esta frase vai inteira para a tela do lojista,
            # e `INSUFFICIENT_STOCK` não diz nada a quem precisa decidir o que
            # fazer com a mercadoria que falta.
            detail=(
                f"Saldo insuficiente de '{product.name}'. "
                f"Disponível: {_amount(previous_balance)}, "
                f"solicitado: {_amount(abs(qty_dec))}."
            )
        )

    # 4. Create Immutable InventoryMovement (Source of Truth Ledger)
    movement = InventoryMovement(
        tenant_id=context.tenant_id,
        store_id=store_id,
        product_id=product_id,
        actor_id=actor_id,
        movement_type=movement_type,
        quantity=qty_dec,
        previous_balance=previous_balance,
        new_balance=new_balance,
        reason=reason,
        correlation_id=correlation_id,
        sale_item_id=sale_item_id,
        origin=origin,
    )
    session.add(movement)

    # 5. Atomic Reliability Integration: AuditEvent + OutboxEvent in single transaction
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=store_id,
        actor_id=actor_id,
        action="inventory.adjust",
        target=f"PRODUCT-{product_id}",
        audit_payload={
            "product_id": str(product_id),
            "movement_type": movement_type.value,
            "quantity": str(qty_dec),
            "previous_balance": str(previous_balance),
            "new_balance": str(new_balance),
            "reason": reason
        },
        aggregate_type="product",
        aggregate_id=str(product_id),
        event_type="inventory.adjusted",
        outbox_payload={
            "tenant_id": str(context.tenant_id),
            "store_id": str(store_id),
            "product_id": str(product_id),
            "movement_type": movement_type.value,
            "quantity": str(qty_dec),
            "previous_balance": str(previous_balance),
            "new_balance": str(new_balance),
            "reason": reason
        },
        correlation_id=correlation_id
    )

    # Sem commit aqui. Este serviço registra um movimento; quem confirma a
    # transação é quem coordena a operação inteira — a rota, para o ajuste
    # manual, e `payment_service` para a baixa da venda, que percorre vários
    # itens. Enquanto o commit vivia aqui dentro, a falha no segundo item de uma
    # venda deixava atrás de si o primeiro item baixado e a venda já marcada
    # como paga, porque o commit do primeiro item levava junto tudo o que
    # estivesse pendente na sessão.
    session.flush()

    # O UPSERT acima é SQL cru: a instância que o ORM tenha em memória para esta
    # linha continua com o saldo anterior até ser relida.
    balance = session.exec(
        select(InventoryBalance).where(
            InventoryBalance.tenant_id == context.tenant_id,
            InventoryBalance.store_id == store_id,
            InventoryBalance.product_id == product_id
        )
    ).one()
    session.refresh(balance)

    return movement, balance, True

class StockCountConflict(HTTPException):
    """O saldo mudou enquanto a prateleira era contada.

    Carrega o estado atual junto da recusa, porque a tela precisa dizer o que
    aconteceu e pedir nova conferência — nunca aceitar em silêncio com a versão
    nova, que seria apagar do estoque a venda que entrou no meio.
    """

    def __init__(self, balance: InventoryBalance, expected_version: int):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "O estoque foi movimentado durante a contagem. "
                    "Confira a prateleira novamente antes de confirmar."
                ),
                "expected_version": expected_version,
                "current_version": balance.version,
                "current_quantity": str(balance.quantity),
            },
        )


def count_stock(
    session: Session,
    context: TenantContext,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    actor_id: uuid.UUID,
    counted_quantity: Union[float, Decimal],
    expected_version: int,
    idempotency_key: str,
    reason: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> tuple[InventoryCount, InventoryBalance, Optional[InventoryMovement]]:
    """A contagem cotidiana: informe o total encontrado, o servidor faz a conta.

    Zero é uma contagem válida e diferente de não preencher — a prateleira vazia
    é um achado. Contagem igual ao saldo registra a conferência e não inventa
    entrada nem saída.
    """
    actor_id = resolve_actor(context, actor_id)
    counted = exact_quantity(counted_quantity, "quantidade contada")
    if counted < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A quantidade contada não pode ser negativa.",
        )
    if context.store_id and store_id != context.store_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Contagem fora da unidade ativa.",
        )

    # Reenvio é repetir o mesmo comando; reaproveitar a chave com outro produto,
    # outra quantidade ou outra versão é comando novo se passando por reenvio, e
    # devolver o resultado antigo ali seria confirmar uma contagem que ninguém
    # fez. A unicidade da chave sozinha não distingue os dois casos — o hash do
    # comando distingue.
    request_hash = reliability_service.compute_request_hash({
        "store_id": str(store_id), "product_id": str(product_id),
        "counted_quantity": str(counted), "expected_version": expected_version,
    })
    existing = session.exec(scope_tenant_query(select(InventoryCount).where(
        InventoryCount.idempotency_key == idempotency_key,
    ), InventoryCount, context)).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Esta confirmação já foi registrada com outro comando. "
                    "Refaça a contagem para gerar uma nova confirmação."
                ),
            )
        balance = get_balance(session, context, store_id, existing.product_id)
        movement = (session.get(InventoryMovement, existing.movement_id)
                    if existing.movement_id else None)
        return existing, balance, movement

    product_query = scope_tenant_query(
        select(Product).where(Product.id == product_id), Product, context,
    )
    product = session.exec(product_query).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Produto não encontrado nesta unidade.",
        )
    if not product.tracks_inventory:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{product.name}' não controla estoque e não pode ser contado.",
        )

    # `FOR UPDATE` não bloqueia linha que não existe, então um produto nunca
    # movimentado não teria o que travar — e uma contagem e um primeiro
    # recebimento simultâneos passariam os dois. A linha é materializada antes,
    # com saldo e versão zero, para que exista algo a bloquear. `DO NOTHING`
    # torna isso seguro entre transações concorrentes: uma cria, a outra não
    # sobrescreve, e ambas serializam no `FOR UPDATE` seguinte.
    session.exec(text("""
        INSERT INTO inventory_balances
            (id, tenant_id, store_id, product_id, quantity, minimum_stock, version, updated_at)
        VALUES (:id, :tenant_id, :store_id, :product_id, 0, 0, 0, :now)
        ON CONFLICT (tenant_id, store_id, product_id) DO NOTHING;
    """), params={
        "id": str(uuid.uuid4()), "tenant_id": str(context.tenant_id),
        "store_id": str(store_id), "product_id": str(product_id),
        "now": datetime.utcnow(),
    })

    # O bloqueio é o que fecha a passagem entre conferir e gravar: uma venda
    # concorrente espera esta linha, e quando a obtiver a versão já terá mudado.
    locked = session.exec(scope_tenant_query(select(InventoryBalance).where(
        InventoryBalance.store_id == store_id,
        InventoryBalance.product_id == product_id,
    ), InventoryBalance, context).with_for_update()).one()

    current_quantity = Decimal(str(locked.quantity))
    current_version = locked.version
    if expected_version != current_version:
        raise StockCountConflict(locked, expected_version)

    difference = counted - current_quantity
    movement = None
    if difference != 0:
        movement, _balance, _created = adjust_stock(
            session=session, context=context, store_id=store_id, product_id=product_id,
            actor_id=actor_id, movement_type=MovementTypeEnum.ADJUSTMENT,
            quantity=difference,
            reason=reason or f"Contagem de estoque: {counted} encontrado(s)",
            correlation_id=correlation_id,
            # A conferência assina o movimento que ela produziu. Sem isto o
            # histórico não distingue a prateleira conferida da diferença
            # lançada à mão, e as duas leem igual.
            origin=MovementOriginEnum.COUNT,
        )

    balance = get_balance(session, context, store_id, product_id)
    record = InventoryCount(
        tenant_id=context.tenant_id, store_id=store_id, product_id=product_id,
        actor_id=actor_id, counted_quantity=counted,
        previous_balance=current_quantity, difference=difference,
        movement_id=movement.id if movement else None,
        balance_version_before=current_version,
        balance_version_after=balance.version if balance.id else current_version,
        reason=reason, idempotency_key=idempotency_key, request_hash=request_hash,
    )
    session.add(record)

    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=store_id,
        actor_id=actor_id, action="inventory.counted",
        target=f"PRODUCT-{product_id}",
        audit_payload={
            "product_id": str(product_id), "counted_quantity": str(counted),
            "previous_balance": str(current_quantity), "difference": str(difference),
            "movement_id": str(movement.id) if movement else None,
        },
        aggregate_type="product", aggregate_id=str(product_id),
        event_type="inventory.counted",
        outbox_payload={
            "tenant_id": str(context.tenant_id), "store_id": str(store_id),
            "product_id": str(product_id), "counted_quantity": str(counted),
            "difference": str(difference),
        },
        correlation_id=correlation_id,
    )
    session.flush()
    return record, balance, movement


def list_holdings(
    session: Session,
    context: TenantContext,
    store_id: uuid.UUID,
    search: Optional[str] = None,
) -> list[dict]:
    """O acervo físico da unidade: tudo que a loja controla, publicado ou não.

    A tela de estoque lia o catálogo vendável, que é a projeção de venda por
    contexto — e uma mercadoria só entra ali depois de publicada em algum
    sortimento. O efeito era que um produto cadastrado, com recebimento
    registrado e controle de estoque ativo, **não aparecia na tela de estoque**
    enquanto ninguém o publicasse.

    Publicação é decisão comercial: ela governa onde o item pode ser vendido, e
    não se ele existe fisicamente na prateleira. Material de uso interno, item
    fora de linha e mercadoria ainda não publicada ocupam espaço, vencem e são
    contados igual — e precisam ser encontrados por quem confere.
    """
    if context.store_id and store_id != context.store_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Consulta de estoque fora da unidade ativa.",
        )
    query = scope_tenant_query(
        select(Product).where(Product.tracks_inventory.is_(True)),
        Product, context,
    )
    if search:
        # O que a busca promete: nome, SKU e código de barras.
        agulha = f"%{search.strip().lower()}%"
        query = query.where(
            func.lower(Product.name).like(agulha)
            | func.lower(Product.sku).like(agulha)
            | func.lower(func.coalesce(Product.barcode, "")).like(agulha)
        )
    produtos = session.exec(query.order_by(Product.name)).all()

    # Abrir a tela de estoque é um dos momentos determinísticos em que a
    # reserva vencida do balcão é recolhida. Idempotente: marca e não faz mais
    # nada (ADR-032).
    expire_stale_reservations(session, context)

    comprometido = {}
    for linha in session.exec(scope_tenant_query(select(
        InventoryReservation.product_id, InventoryReservation.quantity,
    ).where(
        InventoryReservation.store_id == store_id,
        InventoryReservation.status == ReservationStatusEnum.ACTIVE,
    ), InventoryReservation, context)).all():
        product_id, quantidade = linha
        comprometido[product_id] = comprometido.get(product_id, Decimal("0.0000")) + Decimal(str(quantidade))

    saldos = {
        row.product_id: row
        for row in session.exec(scope_tenant_query(select(InventoryBalance).where(
            InventoryBalance.store_id == store_id,
        ), InventoryBalance, context)).all()
    }
    acervo = []
    for produto in produtos:
        saldo = saldos.get(produto.id)
        quantidade = Decimal("0.0000") if saldo is None else Decimal(str(saldo.quantity))
        minimo = Decimal("0.0000") if saldo is None else Decimal(str(saldo.minimum_stock))
        acervo.append({
            "product_id": produto.id,
            "name": produto.name,
            "sku": produto.sku,
            "unit": produto.unit,
            "quantity": quantidade,
            "reserved": comprometido.get(produto.id, Decimal("0.0000")),
            "available": quantidade - comprometido.get(produto.id, Decimal("0.0000")),
            "minimum_stock": minimo,
            # Sem mínimo definido, "abaixo do mínimo" não quer dizer nada: o que
            # existe ali é ausência de política, e a tela precisa distinguir as
            # duas situações em vez de chamar tudo de regular.
            "has_minimum": minimo > 0,
            "is_low_stock": minimo > 0 and quantidade <= minimo,
            "is_out_of_stock": quantidade <= 0,
            "version": 0 if saldo is None else saldo.version,
        })
    return acervo


# ---------------------------------------------------------------- reserva
# Trinta minutos de inatividade, deslizantes: cada alteração da venda renova.
# Carrinho abandonado não pode segurar mercadoria a tarde inteira, e comanda não
# expira — decisão do dono do SaaS em 07/09/2026, registrada no ADR-032.
CART_RESERVATION_TTL = timedelta(minutes=30)


def _lock_balance_row(session: Session, context: TenantContext,
                      store_id: uuid.UUID, product_id: uuid.UUID) -> InventoryBalance:
    """Materializa e bloqueia o saldo, para que duas estações serializem aqui.

    `FOR UPDATE` não bloqueia linha inexistente: sem materializar, dois caixas
    promovendo o primeiro item do mesmo produto passariam os dois.
    """
    session.exec(text("""
        INSERT INTO inventory_balances
            (id, tenant_id, store_id, product_id, quantity, minimum_stock, version, updated_at)
        VALUES (:id, :tenant_id, :store_id, :product_id, 0, 0, 0, :now)
        ON CONFLICT (tenant_id, store_id, product_id) DO NOTHING;
    """), params={
        "id": str(uuid.uuid4()), "tenant_id": str(context.tenant_id),
        "store_id": str(store_id), "product_id": str(product_id),
        "now": datetime.utcnow(),
    })
    return session.exec(scope_tenant_query(select(InventoryBalance).where(
        InventoryBalance.store_id == store_id,
        InventoryBalance.product_id == product_id,
    ), InventoryBalance, context).with_for_update()).one()


def reserved_quantity(session: Session, context: TenantContext, store_id: uuid.UUID,
                      product_id: uuid.UUID, *, ignore_sale_item_id: Optional[uuid.UUID] = None) -> Decimal:
    """Quanto já está prometido a vendas e comandas abertas nesta unidade."""
    query = scope_tenant_query(select(InventoryReservation).where(
        InventoryReservation.store_id == store_id,
        InventoryReservation.product_id == product_id,
        InventoryReservation.status == ReservationStatusEnum.ACTIVE,
    ), InventoryReservation, context)
    if ignore_sale_item_id is not None:
        query = query.where(InventoryReservation.sale_item_id != ignore_sale_item_id)
    return sum((Decimal(str(linha.quantity)) for linha in session.exec(query).all()), Decimal("0.0000"))


def available_to_promise(session: Session, context: TenantContext, store_id: uuid.UUID,
                         product_id: uuid.UUID, *, ignore_sale_item_id: Optional[uuid.UUID] = None) -> Decimal:
    """O que ainda pode ser prometido: prateleira menos compromissos vivos."""
    balance = session.exec(scope_tenant_query(select(InventoryBalance).where(
        InventoryBalance.store_id == store_id,
        InventoryBalance.product_id == product_id,
    ), InventoryBalance, context)).first()
    on_hand = Decimal(str(balance.quantity)) if balance else Decimal("0.0000")
    return on_hand - reserved_quantity(session, context, store_id, product_id,
                                       ignore_sale_item_id=ignore_sale_item_id)


def reserve_for_sale_item(
    session: Session,
    context: TenantContext,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    quantity: Union[float, Decimal],
    *,
    sale_id: uuid.UUID,
    sale_item_id: uuid.UUID,
    source_type: ReservationSourceEnum = ReservationSourceEnum.CART,
    product_name: Optional[str] = None,
) -> InventoryReservation:
    """Promete `quantity` desta mercadoria a uma linha de venda, ou recusa.

    A recusa é a percepção que faltava: ela acontece quando o item entra na
    venda, e não no pagamento. O bloqueio do saldo é o que impede duas estações
    de prometerem as mesmas unidades — a segunda espera a primeira e vê o
    disponível já reduzido.
    """
    pedida = exact_quantity(quantity, field="quantidade")
    if pedida <= 0:
        raise HTTPException(status_code=400, detail="Quantidade reservada precisa ser positiva.")

    balance = _lock_balance_row(session, context, store_id, product_id)
    on_hand = Decimal(str(balance.quantity))
    # A própria linha não disputa consigo mesma: aumentar de 3 para 5 compara o
    # 5 com o disponível, não o 5 somado ao 3 que já era dela.
    comprometido = reserved_quantity(session, context, store_id, product_id,
                                     ignore_sale_item_id=sale_item_id)
    disponivel = on_hand - comprometido
    if pedida > disponivel:
        nome = product_name or "esta mercadoria"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Só há {_humano(disponivel)} disponível de '{nome}'."
                + (f" {_humano(comprometido)} já está em vendas abertas."
                   if comprometido > 0 else "")
            ),
        )

    agora = datetime.utcnow()
    existente = session.exec(scope_tenant_query(select(InventoryReservation).where(
        InventoryReservation.sale_item_id == sale_item_id,
        InventoryReservation.status == ReservationStatusEnum.ACTIVE,
    ), InventoryReservation, context)).first()
    if existente:
        existente.quantity = pedida
        existente.last_activity_at = agora
        existente.expires_at = (agora + CART_RESERVATION_TTL
                                if existente.source_type is ReservationSourceEnum.CART else None)
        session.add(existente)
        session.flush()
        return existente

    reserva = InventoryReservation(
        tenant_id=context.tenant_id, store_id=store_id, product_id=product_id,
        source_type=source_type, sale_id=sale_id, sale_item_id=sale_item_id,
        quantity=pedida, status=ReservationStatusEnum.ACTIVE,
        reserved_at=agora, last_activity_at=agora,
        expires_at=agora + CART_RESERVATION_TTL if source_type is ReservationSourceEnum.CART else None,
    )
    session.add(reserva)
    session.flush()
    return reserva


def _humano(valor: Decimal) -> str:
    """Quantidade como se escreve numa prateleira, sem quatro casas."""
    inteiro = valor.quantize(Decimal("1")) if valor == valor.to_integral_value() else valor.normalize()
    return str(inteiro)


def _encerrar(session: Session, context: TenantContext, *, novo_status: ReservationStatusEnum,
              sale_id: Optional[uuid.UUID] = None,
              sale_item_id: Optional[uuid.UUID] = None) -> int:
    if sale_id is None and sale_item_id is None:
        raise ValueError("Informe a venda ou a linha da venda.")
    query = scope_tenant_query(select(InventoryReservation).where(
        InventoryReservation.status == ReservationStatusEnum.ACTIVE,
    ), InventoryReservation, context)
    if sale_id is not None:
        query = query.where(InventoryReservation.sale_id == sale_id)
    if sale_item_id is not None:
        query = query.where(InventoryReservation.sale_item_id == sale_item_id)
    encerradas = 0
    for reserva in session.exec(query).all():
        reserva.status = novo_status
        reserva.last_activity_at = datetime.utcnow()
        session.add(reserva)
        encerradas += 1
    session.flush()
    return encerradas


def release_reservations(session: Session, context: TenantContext, *,
                         sale_id: Optional[uuid.UUID] = None,
                         sale_item_id: Optional[uuid.UUID] = None) -> int:
    """Devolve o prometido ao disponível: item removido, venda cancelada."""
    return _encerrar(session, context, novo_status=ReservationStatusEnum.RELEASED,
                     sale_id=sale_id, sale_item_id=sale_item_id)


def consume_reservations(session: Session, context: TenantContext, *, sale_id: uuid.UUID) -> int:
    """A venda saiu: o compromisso vira baixa, na mesma transação dela."""
    return _encerrar(session, context, novo_status=ReservationStatusEnum.CONSUMED, sale_id=sale_id)


def expire_stale_reservations(session: Session, context: TenantContext) -> int:
    """Determinístico e idempotente: marca vencidas e não faz mais nada.

    Só alcança carrinho de balcão. Comanda não tem vencimento, e devolver
    estoque em silêncio embaixo de uma mesa aberta seria pior do que a reserva
    presa — o alerta de comanda antiga é outro assunto, e não é este roteiro.
    """
    vencidas = session.exec(scope_tenant_query(select(InventoryReservation).where(
        InventoryReservation.status == ReservationStatusEnum.ACTIVE,
        InventoryReservation.source_type == ReservationSourceEnum.CART,
        InventoryReservation.expires_at.is_not(None),
        InventoryReservation.expires_at < datetime.utcnow(),
    ), InventoryReservation, context)).all()
    for reserva in vencidas:
        reserva.status = ReservationStatusEnum.EXPIRED
        session.add(reserva)
    session.flush()
    return len(vencidas)


def get_balance(session: Session, context: TenantContext, store_id: uuid.UUID, product_id: uuid.UUID) -> InventoryBalance:
    query = select(InventoryBalance).where(
        InventoryBalance.store_id == store_id,
        InventoryBalance.product_id == product_id
    )
    query = scope_tenant_query(query, InventoryBalance, context)
    balance = session.exec(query).first()
    if not balance:
        return _absent_balance(context.tenant_id, store_id, product_id)
    return balance

def list_movements(
    session: Session,
    context: TenantContext,
    store_id: Optional[uuid.UUID] = None,
    product_id: Optional[uuid.UUID] = None
) -> List[InventoryMovement]:
    query = select(InventoryMovement)
    query = scope_tenant_query(query, InventoryMovement, context)
    if store_id:
        query = query.where(InventoryMovement.store_id == store_id)
    if product_id:
        query = query.where(InventoryMovement.product_id == product_id)
    query = query.order_by(InventoryMovement.created_at.desc())
    return session.exec(query).all()


def set_minimum_stock(
    session: Session,
    context: TenantContext,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    minimum_stock: Union[float, Decimal],
) -> InventoryBalance:
    if context.store_id and store_id != context.store_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Configuração fora da unidade ativa.")
    product_query = scope_tenant_query(select(Product).where(Product.id == product_id), Product, context)
    product = session.exec(product_query).first()
    if not product or not product.tracks_inventory:
        raise HTTPException(status_code=404, detail="Produto com controle de estoque não encontrado.")
    minimum = Decimal(str(minimum_stock))
    balance = session.exec(scope_tenant_query(select(InventoryBalance).where(
        InventoryBalance.store_id == store_id,
        InventoryBalance.product_id == product_id,
    ), InventoryBalance, context)).first()
    if not balance:
        balance = InventoryBalance(
            tenant_id=context.tenant_id, store_id=store_id, product_id=product_id,
            quantity=Decimal("0"), minimum_stock=minimum,
        )
        session.add(balance)
    else:
        balance.minimum_stock = minimum
        balance.updated_at = datetime.utcnow()
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=store_id,
        actor_id=resolve_actor(context),
        action="inventory.minimum_stock.updated", target=f"PRODUCT-{product_id}",
        audit_payload={"product_id": str(product_id), "minimum_stock": str(minimum)},
        aggregate_type="product", aggregate_id=str(product_id),
        event_type="inventory.minimum_stock.updated",
        outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(store_id), "product_id": str(product_id), "minimum_stock": str(minimum)},
    )
    session.commit(); session.refresh(balance)
    return balance
