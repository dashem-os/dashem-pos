"""The pinpad is taken by a financial operation not yet proven.

Two axes, and confusing them is the mistake this module exists not to repeat.
Where a command sits on the wire is `commands`; what is known about the money is
here. A command can die on the wire — lease expired, attempts exhausted — while
the charge is still uncertain, and that is exactly when the terminal cannot
accept another. So occupancy is never released by time.

The second trap is subtler: a query saying "not executed" describes the past. An
old suspended process that resumes is a fact of the future. If the installation
changed since the occupancy was taken, the earlier executor keeps the command in
local storage that is not the current installation's, and no deduplication of
ours reaches it — so release demands a recorded neutralization, not financial
evidence alone.

An operation is a transaction *and* what was asked of it. A refund walks on the
charge it reverses (ADR-030) and shares its transaction; without the operation
on the row, a late repeat of the charge's confirmation would free the pinpad
while the refund is still in flight.
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.provider import ProviderTransactionStatusEnum, TefBridgeTerminal
from app.modules.finance.bridge.models import (
    BridgeCommandTypeEnum, ExecutorNeutralizationEnum, FinancialResolutionEnum,
    TefTerminalOccupancy,
)


#: As únicas resoluções que descrevem um desfecho conhecido. `INCERTA` e
#: `NAO_INICIADA` jamais liberam o terminal, por mais tempo que passe.
PROVEN = {
    FinancialResolutionEnum.PROVADA_EXECUTADA,
    FinancialResolutionEnum.PROVADA_NAO_EXECUTADA,
}

#: Só execução ocupa o pinpad. Consulta e cancelamento falam sobre a operação
#: que já o ocupa.
OCCUPYING = {BridgeCommandTypeEnum.START, BridgeCommandTypeEnum.REFUND}


def resolution_for(
    status: ProviderTransactionStatusEnum, *, canceled: Optional[FinancialResolutionEnum],
) -> Optional[FinancialResolutionEnum]:
    """O que uma resposta do provider prova sobre o dinheiro, se prova algo.

    Aprovação e estorno provam que houve movimento; recusa prova que não houve.
    "Cancelada" não é universal: pode ser desfazimento antes da captura ou
    depois dela, e só o adapter de cada provider sabe dizer qual — `canceled` é
    o que ele declarou, e sem declaração a operação segue incerta (§3.5).
    `PROCESSING` e `UNKNOWN` não provam nada.
    """
    if status in {ProviderTransactionStatusEnum.CONFIRMED, ProviderTransactionStatusEnum.REFUNDED}:
        return FinancialResolutionEnum.PROVADA_EXECUTADA
    if status == ProviderTransactionStatusEnum.FAILED:
        return FinancialResolutionEnum.PROVADA_NAO_EXECUTADA
    if status == ProviderTransactionStatusEnum.CANCELED:
        return canceled
    return None


def live_occupancy(session: Session, terminal_id: uuid.UUID) -> Optional[TefTerminalOccupancy]:
    """A ocupação viva do terminal, se houver."""
    return session.exec(select(TefTerminalOccupancy).where(
        TefTerminalOccupancy.bridge_terminal_id == terminal_id,
        TefTerminalOccupancy.released_at.is_(None),
    )).first()


def acquire_occupancy(
    session: Session, *, terminal: TefBridgeTerminal, provider_transaction_id: uuid.UUID,
    operation: BridgeCommandTypeEnum,
) -> TefTerminalOccupancy:
    """Tomar o terminal para esta operação, ou recusar dizendo quem o tem.

    Quem garante a exclusividade é o índice parcial `uq_terminal_occupied`, não
    uma verificação nossa: entre consultar e inserir cabe uma segunda cobrança,
    e um pinpad físico faz uma de cada vez. A colisão é traduzida em 409, e só o
    savepoint desta tentativa é desfeito — a transação de quem chamou é dele.
    """
    if operation not in OCCUPYING:
        raise ValueError(f"{operation.value} não ocupa o terminal.")
    existing = live_occupancy(session, terminal.id)
    if existing is not None:
        raise HTTPException(status_code=409, detail={
            "code": "TERMINAL_OCCUPIED",
            "message": (
                "Esta maquininha está ocupada por outra cobrança. "
                "Consulte ou cancele a operação em andamento antes de cobrar de novo."
            ),
            "provider_transaction_id": str(existing.provider_transaction_id),
            "financial_resolution": existing.financial_resolution.value,
        })
    occupancy = TefTerminalOccupancy(
        tenant_id=terminal.tenant_id, store_id=terminal.store_id,
        bridge_terminal_id=terminal.id, provider_transaction_id=provider_transaction_id,
        operation=operation,
        financial_resolution=FinancialResolutionEnum.INCERTA,
        acquired_epoch=terminal.installation_epoch,
    )
    try:
        with session.begin_nested():
            session.add(occupancy)
            session.flush()
    except IntegrityError as exc:
        # A corrida que a verificação acima não pega. O banco pega.
        raise HTTPException(status_code=409, detail={
            "code": "TERMINAL_OCCUPIED",
            "message": (
                "Esta maquininha acabou de receber outra cobrança. "
                "Consulte a operação em andamento antes de cobrar de novo."
            ),
        }) from exc
    return occupancy


def requires_neutralization(
    session: Session, occupancy: TefTerminalOccupancy,
) -> bool:
    """A instalação mudou desde que esta ocupação nasceu?

    Se mudou, o executor anterior guarda o comando num armazenamento local que
    não é o da instalação atual: ele pode retomar e acionar o SDK, e nenhuma
    deduplicação nossa o alcança.
    """
    terminal = session.get(TefBridgeTerminal, occupancy.bridge_terminal_id)
    return terminal is not None and terminal.installation_epoch != occupancy.acquired_epoch


def release_occupancy(
    session: Session, *, terminal_id: uuid.UUID, provider_transaction_id: uuid.UUID,
    operation: BridgeCommandTypeEnum,
    resolution: FinancialResolutionEnum, reason: str,
    actor_id: Optional[uuid.UUID] = None,
    neutralization: Optional[ExecutorNeutralizationEnum] = None,
) -> bool:
    """Liberar **esta operação** neste terminal. Devolve se liberou.

    Nunca "libere o terminal": a linha só sai se pertencer à operação informada
    — transação e o que foi pedido a ela. Sem essa conferência, o resultado
    tardio de uma cobrança antiga soltaria o terminal que já está ocupado pela
    cobrança seguinte, ou pelo estorno da mesma.

    Tempo não libera nada. Expiração de lease, tentativas esgotadas e resposta
    desconhecida deixam a resolução `INCERTA`, e `INCERTA` não sai daqui.
    """
    if resolution not in PROVEN:
        return False
    occupancy = session.exec(select(TefTerminalOccupancy).where(
        TefTerminalOccupancy.bridge_terminal_id == terminal_id,
        TefTerminalOccupancy.provider_transaction_id == provider_transaction_id,
        TefTerminalOccupancy.operation == operation,
        TefTerminalOccupancy.released_at.is_(None),
    ).with_for_update()).first()
    if occupancy is None:
        # Ou já foi liberada, ou a ocupação viva é de outra operação. Nos dois
        # casos não há nada que esta operação possa liberar.
        return False
    if (
        resolution == FinancialResolutionEnum.PROVADA_NAO_EXECUTADA
        and neutralization is None
        and requires_neutralization(session, occupancy)
    ):
        # "Não executou até agora" não é "não poderá mais executar".
        occupancy.financial_resolution = FinancialResolutionEnum.INCERTA
        return False
    occupancy.financial_resolution = resolution
    occupancy.neutralization = neutralization
    occupancy.released_at = datetime.utcnow()
    occupancy.released_reason = reason[:120]
    occupancy.released_by = actor_id
    session.add(occupancy)
    return True
