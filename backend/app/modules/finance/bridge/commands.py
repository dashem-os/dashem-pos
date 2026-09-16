"""The command queue of one paired bridge.

The command's `id` is its stable identity: redelivery repeats that identity and
never creates a new command, because it is by that identity the bridge
deduplicates before touching the pinpad. Server idempotency does not reach the
device.

Nothing here resolves money. Closing a command closes the command; the
occupancy in `occupancy` stays until someone proves what happened to the charge.

`available_at` is when the command may next be handed out: now, for one waiting
in the queue; the end of the lease, for one already handed out.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import case
from sqlmodel import Session, select

from app.models.provider import TefBridgeTerminal
from app.modules.finance.bridge.models import (
    BridgeCommandClassEnum, BridgeCommandDeliveryStatusEnum, BridgeCommandTypeEnum,
    TefBridgeCommand,
)


LEASE_SECONDS = 30
MAX_ATTEMPTS = 8

EXECUTION_TYPES = {BridgeCommandTypeEnum.START, BridgeCommandTypeEnum.REFUND}


def command_class_for(command_type: BridgeCommandTypeEnum) -> BridgeCommandClassEnum:
    """Classe de transporte, não autorização.

    `CANCEL` e `QUERY` falam sobre a operação em curso e não podem ficar
    bloqueados atrás dela; cancelar continua exigindo autoridade própria, que é
    verificada na rota, não aqui.
    """
    return (
        BridgeCommandClassEnum.EXECUTION
        if command_type in EXECUTION_TYPES
        else BridgeCommandClassEnum.CONTROL
    )


def enqueue_command(
    session: Session, *, terminal: TefBridgeTerminal, provider_transaction_id: uuid.UUID,
    command_type: BridgeCommandTypeEnum, payload: dict, correlation_id: str,
) -> TefBridgeCommand:
    """Colocar um comando na fila daquele terminal, na ordem dele.

    A identidade do comando é o `id` da linha, e é estável: reentrega repete a
    mesma identidade. Criar um comando novo para o mesmo trabalho seria pedir ao
    bridge que cobrasse duas vezes.

    A linha do terminal é travada para numerar: duas emissões para o mesmo
    terminal leriam a mesma última sequência, e a segunda morreria na restrição
    única em vez de entrar na fila atrás da primeira.
    """
    session.exec(select(TefBridgeTerminal.id).where(
        TefBridgeTerminal.id == terminal.id,
    ).with_for_update()).first()
    last = session.exec(select(TefBridgeCommand.sequence).where(
        TefBridgeCommand.bridge_terminal_id == terminal.id,
    ).order_by(TefBridgeCommand.sequence.desc()).limit(1)).first()
    now = datetime.utcnow()
    command = TefBridgeCommand(
        tenant_id=terminal.tenant_id, store_id=terminal.store_id,
        bridge_terminal_id=terminal.id, provider_transaction_id=provider_transaction_id,
        command_type=command_type, command_class=command_class_for(command_type),
        sequence=(last or 0) + 1,
        delivery_status=BridgeCommandDeliveryStatusEnum.PENDING,
        installation_epoch=terminal.installation_epoch,
        available_at=now, attempts=0,
        payload=payload, correlation_id=correlation_id,
        created_at=now, updated_at=now,
    )
    session.add(command)
    session.flush()
    return command


def expire_leases(
    session: Session, *, now: Optional[datetime] = None, terminal_id: Optional[uuid.UUID] = None,
) -> list[uuid.UUID]:
    """Devolver à fila os comandos cujo lease venceu, mantendo a identidade.

    Fechar por tentativas esgotadas fecha o **comando**; a ocupação segue,
    porque o comando ter morrido no fio não diz que a cobrança não saiu.
    """
    observed = now or datetime.utcnow()
    query = select(TefBridgeCommand).where(
        TefBridgeCommand.delivery_status == BridgeCommandDeliveryStatusEnum.LEASED,
        TefBridgeCommand.available_at <= observed,
    )
    if terminal_id is not None:
        query = query.where(TefBridgeCommand.bridge_terminal_id == terminal_id)
    devolvidos: list[uuid.UUID] = []
    for command in session.exec(query.with_for_update(skip_locked=True)).all():
        if command.attempts >= MAX_ATTEMPTS:
            close_command(session, command, reason="ATTEMPTS_EXHAUSTED")
            continue
        command.delivery_status = BridgeCommandDeliveryStatusEnum.PENDING
        command.available_at = observed
        command.updated_at = observed
        session.add(command)
        devolvidos.append(command.id)
    session.flush()
    return devolvidos


def claim_next(
    session: Session, *, terminal_id: uuid.UUID, now: Optional[datetime] = None,
) -> Optional[TefBridgeCommand]:
    """Entregar ao bridge o próximo comando, em lease.

    O lease vencido volta à fila antes, e sai de novo com a mesma identidade
    (I3). Controle antes de execução: um `CANCEL` enfileirado atrás da cobrança
    que ele cancela nunca chegaria a tempo.

    `SKIP LOCKED` protege a reivindicação simultânea, e só ela. Não impede que um
    processo antigo com armazenamento próprio acione o SDK depois do lease — é
    por isso que a ocupação existe e não sai por tempo.
    """
    observed = now or datetime.utcnow()
    expire_leases(session, now=observed, terminal_id=terminal_id)
    command = session.exec(select(TefBridgeCommand).where(
        TefBridgeCommand.bridge_terminal_id == terminal_id,
        TefBridgeCommand.delivery_status == BridgeCommandDeliveryStatusEnum.PENDING,
        TefBridgeCommand.available_at <= observed,
    ).order_by(
        case((TefBridgeCommand.command_class == BridgeCommandClassEnum.CONTROL, 0), else_=1),
        TefBridgeCommand.sequence,
    ).limit(1).with_for_update(skip_locked=True)).first()
    if command is None:
        return None
    command.delivery_status = BridgeCommandDeliveryStatusEnum.LEASED
    command.attempts += 1
    command.available_at = observed + timedelta(seconds=LEASE_SECONDS)
    command.delivered_at = command.delivered_at or observed
    command.updated_at = observed
    session.add(command)
    session.flush()
    return command


def ack_command(session: Session, command: TefBridgeCommand) -> TefBridgeCommand:
    """Confirmar recebimento — sem nunca fazer um estado concluído retroceder.

    Um ACK que chega depois do comando fechado é registrado e não muda nada: o
    resultado já contou a história, e reabrir a entrega convidaria uma segunda
    cobrança do que já foi respondido. ACK depois de o lease vencer tira o
    comando da reentrega: o bridge disse que o tem.
    """
    if command.delivery_status == BridgeCommandDeliveryStatusEnum.CLOSED:
        return command
    command.delivery_status = BridgeCommandDeliveryStatusEnum.ACKED
    command.acked_at = command.acked_at or datetime.utcnow()
    command.updated_at = datetime.utcnow()
    session.add(command)
    return command


def close_command(
    session: Session, command: TefBridgeCommand, *, reason: str,
) -> TefBridgeCommand:
    """Fechar o comando. Isto não resolve a operação financeira.

    Concluir uma consulta, ou esgotar as tentativas de uma cobrança, encerra o
    comando e mais nada: a ocupação continua de pé até alguém provar o que
    aconteceu com o dinheiro.
    """
    if command.delivery_status != BridgeCommandDeliveryStatusEnum.CLOSED:
        command.delivery_status = BridgeCommandDeliveryStatusEnum.CLOSED
        command.closed_at = datetime.utcnow()
        command.closed_reason = reason[:80]
        command.updated_at = datetime.utcnow()
        session.add(command)
    return command


def record_result(session: Session, command: TefBridgeCommand) -> TefBridgeCommand:
    """Chegou resultado deste comando: ele foi recebido, diga o ACK o que disser.

    Resultado antes do ACK fecha o comando; resultado repetido sobre comando
    fechado não muda nada no fio. O que o resultado diz sobre o dinheiro é
    aplicado à transação por quem chamou, não aqui.
    """
    return close_command(session, command, reason="RESULT_RECEIVED")
