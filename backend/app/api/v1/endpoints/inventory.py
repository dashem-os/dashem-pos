import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from decimal import Decimal
from pydantic import BaseModel, Field
from sqlmodel import Session
from app.core.database import get_session
from app.core.context import TenantContext, get_tenant_context, resolve_actor
from app.models.catalog import (
    InventoryBalance, InventoryCount, InventoryMovement, MovementTypeEnum,
)
from app.services import inventory_service, reliability_service

router = APIRouter()

# A rota é o caminho do lojista, e nele não existe "dar baixa de venda". A baixa
# pertence ao fluxo de venda, que a executa dentro da transação da quitação; um
# `POST` manual com `SALE` era uma operação se passando por outra, com o mesmo
# rótulo no histórico e nenhuma venda por trás.
MANUAL_MOVEMENTS = frozenset({
    MovementTypeEnum.PURCHASE, MovementTypeEnum.LOSS,
})

class StockAdjustDTO(BaseModel):
    store_id: uuid.UUID
    product_id: uuid.UUID
    actor_id: uuid.UUID
    movement_type: MovementTypeEnum
    quantity: float
    reason: Optional[str] = None

class StockAdjustResponse(BaseModel):
    movement: Optional[InventoryMovement]
    balance: InventoryBalance
    movement_created: bool


class MinimumStockDTO(BaseModel):
    store_id: uuid.UUID
    product_id: uuid.UUID
    minimum_stock: float

@router.post("/adjust", response_model=StockAdjustResponse)
def adjust_stock_endpoint(
    data: StockAdjustDTO,
    context: TenantContext = Depends(get_tenant_context),
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID"),
    session: Session = Depends(get_session)
):
    if data.movement_type == MovementTypeEnum.ADJUSTMENT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Diferença de estoque se registra contando a prateleira. "
                "O ajuste assinado tem rota e autorização próprias."
            ),
        )
    if data.movement_type == MovementTypeEnum.RETURN:
        # Aceitar devolução por aqui abriria uma porta paralela para o mesmo
        # estoque: a devolução vinculada recusa o que não tem baixa comprovada,
        # e uma chamada manual acrescentaria a mesma mercadoria sem origem, sem
        # teto e sem prova. Proteção com caminho alternativo não é proteção.
        # A recusa aponta o caminho normal. Nomear a exceção aqui teria o mesmo
        # efeito que teve na devolução vinculada: oferecida na porta, ela vira
        # rotina. O procedimento excepcional é apresentado ao responsável
        # autorizado depois da conferência, não antes dela.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Devolução de cliente se registra no histórico da venda de "
                "origem, que é de onde saem o limite e o histórico."
            ),
        )
    if data.movement_type not in MANUAL_MOVEMENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Baixa de venda é registrada pela quitação da venda, não por "
                "movimentação manual de estoque."
            ),
        )
    actor_id = resolve_actor(context, data.actor_id)
    # Check Idempotency if key header is provided
    if x_idempotency_key:
        is_cached, status_code, body = reliability_service.check_idempotency(
            session=session,
            tenant_id=context.tenant_id,
            actor_id=actor_id,
            operation="POST /api/v1/inventory/adjust",
            idempotency_key=x_idempotency_key,
            request_payload=data.dict()
        )
        if is_cached and status_code and body:
            return body

    movement, balance, created = inventory_service.adjust_stock(
        session=session,
        context=context,
        store_id=data.store_id,
        product_id=data.product_id,
        actor_id=actor_id,
        movement_type=data.movement_type,
        quantity=data.quantity,
        reason=data.reason,
        correlation_id=x_correlation_id
    )

    response_data = {
        "movement": movement.dict() if movement else None,
        "balance": balance.dict(),
        "movement_created": created
    }

    # Save Idempotency record if key header was provided
    if x_idempotency_key:
        reliability_service.save_idempotency_record(
            session=session,
            tenant_id=context.tenant_id,
            actor_id=actor_id,
            operation="POST /api/v1/inventory/adjust",
            idempotency_key=x_idempotency_key,
            request_payload=data.dict(),
            response_status=200,
            response_body=response_data
        )

    session.commit()
    return response_data

class StockCountDTO(BaseModel):
    store_id: uuid.UUID
    product_id: uuid.UUID
    actor_id: uuid.UUID
    # Obrigatório e não negativo. Zero é uma contagem: prateleira vazia é achado,
    # e é diferente de não preencher o campo — que o Pydantic recusa aqui.
    counted_quantity: Decimal = Field(ge=0)
    # A versão que a pessoa tinha à vista quando foi contar. Zero quando o
    # produto ainda não tem linha de saldo.
    expected_version: int = Field(ge=0)
    reason: Optional[str] = None


class StockCountResponse(BaseModel):
    count: InventoryCount
    balance: InventoryBalance
    movement: Optional[InventoryMovement]


@router.post("/count", response_model=StockCountResponse)
def count_stock_endpoint(
    data: StockCountDTO,
    context: TenantContext = Depends(get_tenant_context),
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    x_correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID"),
    session: Session = Depends(get_session),
):
    """Contar a prateleira: informe o total encontrado, o servidor faz a conta.

    Conferência e gravação acontecem na mesma transação, com a linha do saldo
    bloqueada: não há espaço para uma venda entrar entre verificar a versão e
    escrever o resultado.
    """
    count, balance, movement = inventory_service.count_stock(
        session=session, context=context, store_id=data.store_id,
        product_id=data.product_id, actor_id=data.actor_id,
        counted_quantity=data.counted_quantity,
        expected_version=data.expected_version,
        idempotency_key=idempotency_key, reason=data.reason,
        correlation_id=x_correlation_id,
    )
    session.commit()
    session.refresh(count)
    session.refresh(balance)
    if movement is not None:
        session.refresh(movement)
    return {"count": count, "balance": balance, "movement": movement}


class TechnicalAdjustmentDTO(BaseModel):
    store_id: uuid.UUID
    product_id: uuid.UUID
    actor_id: uuid.UUID
    # A única operação que carrega o próprio sinal, porque ela *é* a diferença.
    difference: Decimal
    reason: str = Field(min_length=3)


@router.post("/technical-adjustment", response_model=StockAdjustResponse)
def technical_adjustment_endpoint(
    data: TechnicalAdjustmentDTO,
    context: TenantContext = Depends(get_tenant_context),
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID"),
    session: Session = Depends(get_session),
):
    """A diferença lançada à mão, para quando a contagem não resolve.

    Exige `inventory.adjust.technical`, que não acompanha `inventory.adjust`:
    lançar diferença assinada contorna a conferência da prateleira, e isso é
    autoridade de administração do tenant, não de operação de loja.
    """
    actor_id = resolve_actor(context, data.actor_id)
    movement, balance, created = inventory_service.adjust_stock(
        session=session, context=context, store_id=data.store_id,
        product_id=data.product_id, actor_id=actor_id,
        movement_type=MovementTypeEnum.ADJUSTMENT, quantity=data.difference,
        reason=data.reason, correlation_id=x_correlation_id,
    )
    response_data = {
        "movement": movement.dict() if movement else None,
        "balance": balance.dict(),
        "movement_created": created,
    }
    if x_idempotency_key:
        reliability_service.save_idempotency_record(
            session=session, tenant_id=context.tenant_id, actor_id=actor_id,
            operation="POST /api/v1/inventory/technical-adjustment",
            idempotency_key=x_idempotency_key, request_payload=data.dict(),
            response_status=200, response_body=response_data,
        )
    session.commit()
    return response_data


class StockHolding(BaseModel):
    """Uma linha do acervo físico, publicada ou não."""

    product_id: uuid.UUID
    name: str
    sku: str
    unit: str
    quantity: Decimal
    minimum_stock: Decimal
    has_minimum: bool
    is_low_stock: bool
    is_out_of_stock: bool
    version: int


@router.get("/holdings", response_model=List[StockHolding])
def list_holdings_endpoint(
    store_id: uuid.UUID,
    search: Optional[str] = None,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    """O acervo físico da unidade, e não a projeção de venda.

    Publicação decide onde o item pode ser vendido; ela não decide se ele existe
    na prateleira. Quem confere estoque precisa encontrar o que está lá.
    """
    return inventory_service.list_holdings(session, context, store_id, search)


@router.get("/balance", response_model=InventoryBalance)
def get_balance_endpoint(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return inventory_service.get_balance(session, context, store_id=store_id, product_id=product_id)

@router.get("/movements", response_model=List[InventoryMovement])
def list_movements_endpoint(
    store_id: Optional[uuid.UUID] = None,
    product_id: Optional[uuid.UUID] = None,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return inventory_service.list_movements(session, context, store_id=store_id, product_id=product_id)


@router.put("/minimum", response_model=InventoryBalance)
def set_minimum_stock_endpoint(
    data: MinimumStockDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    if data.minimum_stock < 0:
        raise HTTPException(status_code=400, detail="minimum_stock não pode ser negativo.")
    return inventory_service.set_minimum_stock(
        session, context, data.store_id, data.product_id, data.minimum_stock,
    )
