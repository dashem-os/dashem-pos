"""A maquininha ocupada, e o que não basta para desocupá-la.

Estes testes defendem uma regra só, dita de várias maneiras: **tempo não prova
ausência de cobrança**. Um comando pode vencer o lease, esgotar as tentativas e
morrer no fio enquanto o dinheiro segue incerto — e é exatamente aí que o
terminal não pode aceitar outra cobrança.

E defendem uma segunda, que custou uma revisão inteira para aparecer: consulta
dizendo "não executou" descreve o passado. Um processo antigo suspenso que
retoma é um fato do futuro. Se a instalação mudou desde que a ocupação nasceu, o
executor de antes guarda o comando num armazenamento local que não é o da
instalação atual — e nenhuma deduplicação nossa o alcança.
"""

import threading
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.identity import Register, Store, Tenant, TenantStatusEnum, User
from app.models.negotiation import CheckoutNegotiation, PaymentIntent
from app.models.payment import PaymentMethodEnum
from app.models.provider import (
    BridgeTerminalStatusEnum, PaymentProviderConfiguration,
    ProviderConfigurationStatusEnum, ProviderTransaction, ProviderTransactionStatusEnum,
    TefBridgeTerminal,
)
from app.modules.finance.bridge import commands, occupancy
from app.modules.finance.bridge.models import (
    BridgeCommandDeliveryStatusEnum, BridgeCommandTypeEnum, ExecutorNeutralizationEnum,
    FinancialResolutionEnum, TefBridgeCommand, TefTerminalOccupancy,
)


def _cenario(session: Session, sufixo: str, *, transacoes: int = 2):
    """Um caixa com bridge pareado e algumas cobranças prontas para disputar."""
    tenant = Tenant(name=f"Ocupacao {sufixo}", slug=f"ocupacao-{sufixo}", status=TenantStatusEnum.ACTIVE)
    operador = User(full_name="Operadora do balcão")
    session.add(tenant); session.add(operador); session.flush()
    store = Store(tenant_id=tenant.id, name="Matriz", code=f"OC-{sufixo}")
    session.add(store); session.flush()
    register = Register(tenant_id=tenant.id, store_id=store.id, name="Caixa", code=f"OCCX-{sufixo}")
    configuracao = PaymentProviderConfiguration(
        tenant_id=tenant.id, store_id=store.id, provider_code=f"OCUPACAO-{sufixo}",
        status=ProviderConfigurationStatusEnum.ACTIVE, configured_by=operador.id,
    )
    negociacao = CheckoutNegotiation(
        tenant_id=tenant.id, store_id=store.id, scope_key=f"OCUPACAO:{sufixo}",
        subtotal=Decimal("100.00"), total_due=Decimal("100.00"), source_version=1,
        opened_by=operador.id, open_idempotency_key=f"oc-neg-{sufixo}", open_request_hash="n" * 64,
    )
    session.add(register); session.add(configuracao); session.add(negociacao); session.flush()
    terminal = TefBridgeTerminal(
        tenant_id=tenant.id, store_id=store.id, register_id=register.id,
        provider_configuration_id=configuracao.id, terminal_code=f"OCT-{sufixo}",
        pairing_secret_hash="h" * 64, paired_by=operador.id,
        status=BridgeTerminalStatusEnum.ONLINE, installation_epoch=0,
    )
    session.add(terminal); session.flush()
    cobrancas = []
    for indice in range(transacoes):
        intent = PaymentIntent(
            tenant_id=tenant.id, store_id=store.id, negotiation_id=negociacao.id,
            method=PaymentMethodEnum.CREDIT_CARD, amount=Decimal("50.00"),
            provider="OCUPACAO", idempotency_key=f"oc-intent-{sufixo}-{indice}",
            request_hash="i" * 64, created_by=operador.id,
        )
        session.add(intent); session.flush()
        transacao = ProviderTransaction(
            tenant_id=tenant.id, store_id=store.id, payment_intent_id=intent.id,
            provider_configuration_id=configuracao.id, bridge_terminal_id=terminal.id,
            provider_code=configuracao.provider_code, adapter_version="1.0.0",
            correlation_id=f"oc-corr-{sufixo}-{indice}",
            idempotency_key=f"oc-tx-{sufixo}-{indice}", request_hash="r" * 64,
            created_by=operador.id,
        )
        session.add(transacao); session.flush()
        cobrancas.append(transacao)
    return terminal, cobrancas, operador


def test_maquininha_ocupada_recusa_a_segunda_cobranca():
    """Um pinpad físico faz uma de cada vez, e a recusa nomeia quem o tem."""
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (primeira, segunda), _ = _cenario(session, sufixo)
        occupancy.acquire_occupancy(session, terminal=terminal, provider_transaction_id=primeira.id, operation=BridgeCommandTypeEnum.START)
        with pytest.raises(HTTPException) as erro:
            occupancy.acquire_occupancy(session, terminal=terminal, provider_transaction_id=segunda.id, operation=BridgeCommandTypeEnum.START)
        assert erro.value.status_code == 409
        assert erro.value.detail["code"] == "TERMINAL_OCCUPIED"
        assert erro.value.detail["provider_transaction_id"] == str(primeira.id)
        session.rollback()


def test_ocupacao_liberada_nao_deixa_o_caixa_travado():
    """`released_at` preenchido tem de soltar o terminal de verdade.

    Com o terminal como chave primária, a linha liberada continuava ocupando a
    chave e o caixa nunca mais aceitava cobrança. O cadeado é o índice parcial.
    """
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (primeira, segunda), operador = _cenario(session, sufixo)
        occupancy.acquire_occupancy(session, terminal=terminal, provider_transaction_id=primeira.id, operation=BridgeCommandTypeEnum.START)
        assert occupancy.release_occupancy(
            session, terminal_id=terminal.id, provider_transaction_id=primeira.id,
            operation=BridgeCommandTypeEnum.START,
            resolution=FinancialResolutionEnum.PROVADA_EXECUTADA,
            reason="Adquirente confirmou.", actor_id=operador.id,
        ) is True
        session.flush()
        nova = occupancy.acquire_occupancy(session, terminal=terminal, provider_transaction_id=segunda.id, operation=BridgeCommandTypeEnum.START)
        assert nova.provider_transaction_id == segunda.id
        session.rollback()


def test_resultado_tardio_de_outra_operacao_nao_solta_a_ocupacao_vigente():
    """O desfecho da cobrança antiga não desocupa o terminal da cobrança nova."""
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (antiga, vigente), operador = _cenario(session, sufixo)
        occupancy.acquire_occupancy(session, terminal=terminal, provider_transaction_id=antiga.id, operation=BridgeCommandTypeEnum.START)
        occupancy.release_occupancy(
            session, terminal_id=terminal.id, provider_transaction_id=antiga.id,
            operation=BridgeCommandTypeEnum.START,
            resolution=FinancialResolutionEnum.PROVADA_EXECUTADA, reason="Confirmada.",
            actor_id=operador.id,
        )
        session.flush()
        occupancy.acquire_occupancy(session, terminal=terminal, provider_transaction_id=vigente.id, operation=BridgeCommandTypeEnum.START)
        # A resposta atrasada da antiga chega agora. Não é dela o terminal.
        assert occupancy.release_occupancy(
            session, terminal_id=terminal.id, provider_transaction_id=antiga.id,
            operation=BridgeCommandTypeEnum.START,
            resolution=FinancialResolutionEnum.PROVADA_NAO_EXECUTADA,
            reason="Resposta tardia da cobrança anterior.", actor_id=operador.id,
        ) is False
        viva = occupancy.live_occupancy(session, terminal.id)
        assert viva is not None and viva.provider_transaction_id == vigente.id
        session.rollback()


def test_tempo_nunca_libera_o_terminal():
    """Lease vencido e tentativas esgotadas fecham o comando, não a operação."""
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (cobranca, _), operador = _cenario(session, sufixo)
        occupancy.acquire_occupancy(session, terminal=terminal, provider_transaction_id=cobranca.id, operation=BridgeCommandTypeEnum.START)
        comando = commands.enqueue_command(
            session, terminal=terminal, provider_transaction_id=cobranca.id,
            command_type=BridgeCommandTypeEnum.START, payload={}, correlation_id="oc-corr",
        )
        comando.delivery_status = BridgeCommandDeliveryStatusEnum.LEASED
        comando.attempts = commands.MAX_ATTEMPTS
        comando.available_at = datetime.utcnow() - timedelta(seconds=1)
        session.add(comando); session.flush()

        commands.expire_leases(session)
        session.flush()
        assert comando.delivery_status == BridgeCommandDeliveryStatusEnum.CLOSED
        assert comando.closed_reason == "ATTEMPTS_EXHAUSTED"

        # O comando morreu no fio. A cobrança continua incerta, e o terminal, tomado.
        viva = occupancy.live_occupancy(session, terminal.id)
        assert viva is not None
        assert viva.financial_resolution == FinancialResolutionEnum.INCERTA
        assert occupancy.release_occupancy(
            session, terminal_id=terminal.id, provider_transaction_id=cobranca.id,
            operation=BridgeCommandTypeEnum.START,
            resolution=FinancialResolutionEnum.INCERTA,
            reason="Tentativas esgotadas.", actor_id=operador.id,
        ) is False
        session.rollback()


def test_consulta_dizendo_nao_executou_nao_basta_apos_troca_de_instalacao():
    """"Não executou até agora" não é "não poderá mais executar".

    O processo antigo pode estar suspenso com o comando na mão. Liberar aqui
    seria autorizar a cobrança seguinte para depois ver a primeira acontecer.
    """
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (cobranca, _), operador = _cenario(session, sufixo)
        occupancy.acquire_occupancy(session, terminal=terminal, provider_transaction_id=cobranca.id, operation=BridgeCommandTypeEnum.START)
        # Outra instalação assumiu o terminal: o executor de antes tem
        # armazenamento local próprio, que a instalação nova não enxerga.
        terminal.installation_epoch = 1
        terminal.active_installation_id = uuid.uuid4()
        session.add(terminal); session.flush()

        assert occupancy.release_occupancy(
            session, terminal_id=terminal.id, provider_transaction_id=cobranca.id,
            operation=BridgeCommandTypeEnum.START,
            resolution=FinancialResolutionEnum.PROVADA_NAO_EXECUTADA,
            reason="Consulta disse que não executou.", actor_id=operador.id,
        ) is False
        viva = occupancy.live_occupancy(session, terminal.id)
        assert viva is not None
        assert viva.financial_resolution == FinancialResolutionEnum.INCERTA
        session.rollback()


def test_neutralizacao_registrada_libera_o_que_a_consulta_sozinha_nao_liberava():
    """Com o executor anterior neutralizado, a evidência passa a bastar."""
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (cobranca, seguinte), operador = _cenario(session, sufixo)
        occupancy.acquire_occupancy(session, terminal=terminal, provider_transaction_id=cobranca.id, operation=BridgeCommandTypeEnum.START)
        terminal.installation_epoch = 1
        session.add(terminal); session.flush()

        assert occupancy.release_occupancy(
            session, terminal_id=terminal.id, provider_transaction_id=cobranca.id,
            operation=BridgeCommandTypeEnum.START,
            resolution=FinancialResolutionEnum.PROVADA_NAO_EXECUTADA,
            reason="Consulta e desinstalação atestada.", actor_id=operador.id,
            neutralization=ExecutorNeutralizationEnum.ATTESTED_DECOMMISSIONED,
        ) is True
        session.flush()
        nova = occupancy.acquire_occupancy(session, terminal=terminal, provider_transaction_id=seguinte.id, operation=BridgeCommandTypeEnum.START)
        assert nova.provider_transaction_id == seguinte.id
        session.rollback()


def test_mesma_instalacao_libera_sem_neutralizacao():
    """Sem troca de instalação, a deduplicação local do próprio bridge cobre."""
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (cobranca, _), operador = _cenario(session, sufixo)
        occupancy.acquire_occupancy(session, terminal=terminal, provider_transaction_id=cobranca.id, operation=BridgeCommandTypeEnum.START)
        assert occupancy.release_occupancy(
            session, terminal_id=terminal.id, provider_transaction_id=cobranca.id,
            operation=BridgeCommandTypeEnum.START,
            resolution=FinancialResolutionEnum.PROVADA_NAO_EXECUTADA,
            reason="Consulta ao provedor: não executou.", actor_id=operador.id,
        ) is True
        session.rollback()


def test_fechar_a_consulta_nao_resolve_a_operacao_consultada():
    """Concluir um `QUERY` encerra o comando e mais nada."""
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (cobranca, _), _ = _cenario(session, sufixo)
        occupancy.acquire_occupancy(session, terminal=terminal, provider_transaction_id=cobranca.id, operation=BridgeCommandTypeEnum.START)
        consulta = commands.enqueue_command(
            session, terminal=terminal, provider_transaction_id=cobranca.id,
            command_type=BridgeCommandTypeEnum.QUERY, payload={}, correlation_id="oc-q",
        )
        commands.close_command(session, consulta, reason="QUERY_ANSWERED_UNKNOWN")
        session.flush()
        assert consulta.delivery_status == BridgeCommandDeliveryStatusEnum.CLOSED
        viva = occupancy.live_occupancy(session, terminal.id)
        assert viva is not None
        assert viva.financial_resolution == FinancialResolutionEnum.INCERTA
        session.rollback()


def test_ack_tardio_nao_reabre_comando_concluido():
    """O resultado já contou a história; reabrir convidaria a cobrar de novo."""
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (cobranca, _), _ = _cenario(session, sufixo)
        comando = commands.enqueue_command(
            session, terminal=terminal, provider_transaction_id=cobranca.id,
            command_type=BridgeCommandTypeEnum.START, payload={}, correlation_id="oc-s",
        )
        commands.close_command(session, comando, reason="RESULT_APPLIED")
        session.flush()
        commands.ack_command(session, comando)
        session.flush()
        assert comando.delivery_status == BridgeCommandDeliveryStatusEnum.CLOSED
        session.rollback()


def test_duas_sessoes_disputando_o_mesmo_terminal_so_uma_ocupa():
    """A corrida que a verificação da aplicação não pega. O banco pega.

    A primeira sessão insere e segura a linha sem confirmar. A segunda não a
    enxerga — a verificação prévia passa — e fica esperando no índice único.
    Quando a primeira confirma, a segunda recebe a colisão, e a colisão vira
    409 sem desfazer a transação de quem chamou: só o savepoint da tentativa.
    """
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (uma, outra), _ = _cenario(session, sufixo)
        session.commit()
        terminal_id, uma_id, outra_id = terminal.id, uma.id, outra.id

    desfecho: dict = {}

    def segunda_cobranca():
        with Session(engine) as sessao_b:
            set_platform_db_context(sessao_b)
            terminal_b = sessao_b.get(TefBridgeTerminal, terminal_id)
            assert occupancy.live_occupancy(sessao_b, terminal_id) is None
            try:
                occupancy.acquire_occupancy(
                    sessao_b, terminal=terminal_b, provider_transaction_id=outra_id,
                    operation=BridgeCommandTypeEnum.START,
                )
                sessao_b.commit()
                desfecho["aceita"] = True
            except HTTPException as erro:
                desfecho["status"] = erro.status_code
                # A transação de quem chamou continua de pé depois da colisão.
                desfecho["sessao_utilizavel"] = sessao_b.get(TefBridgeTerminal, terminal_id) is not None

    with Session(engine) as sessao_a:
        set_platform_db_context(sessao_a)
        terminal_a = sessao_a.get(TefBridgeTerminal, terminal_id)
        occupancy.acquire_occupancy(
            sessao_a, terminal=terminal_a, provider_transaction_id=uma_id,
            operation=BridgeCommandTypeEnum.START,
        )
        concorrente = threading.Thread(target=segunda_cobranca)
        concorrente.start()
        # Tempo para a segunda chegar ao índice e ficar presa nele. Se ela não
        # chegou, o teste ainda prova a recusa, só que pela verificação prévia —
        # e a asserção de visibilidade dentro dela reprova esse caso.
        concorrente.join(timeout=1.5)
        assert concorrente.is_alive(), "a segunda cobrança deveria estar esperando no índice"
        sessao_a.commit()
        concorrente.join(timeout=10)

    assert desfecho == {"status": 409, "sessao_utilizavel": True}
    with Session(engine) as session:
        set_platform_db_context(session)
        vivas = session.exec(select(TefTerminalOccupancy).where(
            TefTerminalOccupancy.bridge_terminal_id == terminal_id,
            TefTerminalOccupancy.released_at.is_(None),
        )).all()
        assert [viva.provider_transaction_id for viva in vivas] == [uma_id]


def test_resposta_da_cobranca_nao_solta_o_estorno_da_mesma_transacao():
    """O estorno anda sobre a cobrança que reverte e divide a transação com ela.

    Uma confirmação repetida da cobrança, chegando com o estorno em voo, fala de
    outra operação: o terminal segue com o estorno.
    """
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (cobranca, _), operador = _cenario(session, sufixo)
        occupancy.acquire_occupancy(
            session, terminal=terminal, provider_transaction_id=cobranca.id,
            operation=BridgeCommandTypeEnum.REFUND,
        )
        assert occupancy.release_occupancy(
            session, terminal_id=terminal.id, provider_transaction_id=cobranca.id,
            operation=BridgeCommandTypeEnum.START,
            resolution=FinancialResolutionEnum.PROVADA_EXECUTADA,
            reason="Confirmação repetida da cobrança.", actor_id=operador.id,
        ) is False
        viva = occupancy.live_occupancy(session, terminal.id)
        assert viva is not None and viva.operation == BridgeCommandTypeEnum.REFUND
        # E a resposta do próprio estorno solta.
        assert occupancy.release_occupancy(
            session, terminal_id=terminal.id, provider_transaction_id=cobranca.id,
            operation=BridgeCommandTypeEnum.REFUND,
            resolution=FinancialResolutionEnum.PROVADA_EXECUTADA,
            reason="Estorno confirmado.", actor_id=operador.id,
        ) is True
        session.rollback()


def test_consulta_e_cancelamento_nao_ocupam_o_terminal():
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (cobranca, _), _ = _cenario(session, sufixo)
        for controle in (BridgeCommandTypeEnum.QUERY, BridgeCommandTypeEnum.CANCEL):
            with pytest.raises(ValueError):
                occupancy.acquire_occupancy(
                    session, terminal=terminal, provider_transaction_id=cobranca.id, operation=controle,
                )
        session.rollback()


@pytest.mark.parametrize(("status", "declarado", "esperado"), [
    (ProviderTransactionStatusEnum.CONFIRMED, None, FinancialResolutionEnum.PROVADA_EXECUTADA),
    (ProviderTransactionStatusEnum.REFUNDED, None, FinancialResolutionEnum.PROVADA_EXECUTADA),
    (ProviderTransactionStatusEnum.FAILED, None, FinancialResolutionEnum.PROVADA_NAO_EXECUTADA),
    # "Cancelada" só prova o que o adapter do provider declarou que prova.
    (ProviderTransactionStatusEnum.CANCELED, None, None),
    (ProviderTransactionStatusEnum.CANCELED, FinancialResolutionEnum.PROVADA_NAO_EXECUTADA,
     FinancialResolutionEnum.PROVADA_NAO_EXECUTADA),
    (ProviderTransactionStatusEnum.CANCELED, FinancialResolutionEnum.PROVADA_EXECUTADA,
     FinancialResolutionEnum.PROVADA_EXECUTADA),
    # Não saber, e estar a caminho, não provam nada — declare o adapter o que for.
    (ProviderTransactionStatusEnum.UNKNOWN, FinancialResolutionEnum.PROVADA_NAO_EXECUTADA, None),
    (ProviderTransactionStatusEnum.PROCESSING, FinancialResolutionEnum.PROVADA_NAO_EXECUTADA, None),
    (ProviderTransactionStatusEnum.CREATED, None, None),
])
def test_o_que_cada_resposta_prova_sobre_o_dinheiro(status, declarado, esperado):
    assert occupancy.resolution_for(status, canceled=declarado) == esperado


def test_lease_vencido_entrega_de_novo_o_mesmo_comando():
    """Reentregar é repetir a identidade, nunca criar comando novo (I3)."""
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (cobranca, _), _ = _cenario(session, sufixo)
        emitido = commands.enqueue_command(
            session, terminal=terminal, provider_transaction_id=cobranca.id,
            command_type=BridgeCommandTypeEnum.START, payload={}, correlation_id="oc-l",
        )
        agora = datetime.utcnow()
        primeira = commands.claim_next(session, terminal_id=terminal.id, now=agora)
        assert primeira.id == emitido.id and primeira.attempts == 1
        assert primeira.delivery_status == BridgeCommandDeliveryStatusEnum.LEASED
        # Dentro do lease, ninguém mais o recebe.
        assert commands.claim_next(session, terminal_id=terminal.id, now=agora + timedelta(seconds=5)) is None
        depois = agora + timedelta(seconds=commands.LEASE_SECONDS + 1)
        segunda = commands.claim_next(session, terminal_id=terminal.id, now=depois)
        assert segunda.id == emitido.id and segunda.attempts == 2
        comandos = session.exec(select(TefBridgeCommand).where(
            TefBridgeCommand.bridge_terminal_id == terminal.id,
        )).all()
        assert len(comandos) == 1
        session.rollback()


def test_controle_sai_antes_da_execucao_que_ele_cita():
    """Um cancelamento atrás da cobrança que cancela nunca chegaria a tempo."""
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (cobranca, _), _ = _cenario(session, sufixo)
        inicio = commands.enqueue_command(
            session, terminal=terminal, provider_transaction_id=cobranca.id,
            command_type=BridgeCommandTypeEnum.START, payload={}, correlation_id="oc-c1",
        )
        cancelamento = commands.enqueue_command(
            session, terminal=terminal, provider_transaction_id=cobranca.id,
            command_type=BridgeCommandTypeEnum.CANCEL, payload={}, correlation_id="oc-c2",
        )
        assert (inicio.sequence, cancelamento.sequence) == (1, 2)
        agora = datetime.utcnow()
        assert commands.claim_next(session, terminal_id=terminal.id, now=agora).id == cancelamento.id
        assert commands.claim_next(session, terminal_id=terminal.id, now=agora).id == inicio.id
        session.rollback()


def test_ack_depois_do_lease_vencido_tira_o_comando_da_reentrega():
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (cobranca, _), _ = _cenario(session, sufixo)
        commands.enqueue_command(
            session, terminal=terminal, provider_transaction_id=cobranca.id,
            command_type=BridgeCommandTypeEnum.START, payload={}, correlation_id="oc-a",
        )
        agora = datetime.utcnow()
        entregue = commands.claim_next(session, terminal_id=terminal.id, now=agora)
        commands.ack_command(session, entregue)
        session.flush()
        depois = agora + timedelta(seconds=commands.LEASE_SECONDS + 1)
        assert commands.claim_next(session, terminal_id=terminal.id, now=depois) is None
        assert entregue.delivery_status == BridgeCommandDeliveryStatusEnum.ACKED
        session.rollback()


def test_resultado_antes_do_ack_fecha_e_nao_reabre():
    sufixo = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal, (cobranca, _), _ = _cenario(session, sufixo)
        commands.enqueue_command(
            session, terminal=terminal, provider_transaction_id=cobranca.id,
            command_type=BridgeCommandTypeEnum.START, payload={}, correlation_id="oc-r",
        )
        entregue = commands.claim_next(session, terminal_id=terminal.id)
        commands.record_result(session, entregue)
        commands.ack_command(session, entregue)
        commands.record_result(session, entregue)
        session.flush()
        assert entregue.delivery_status == BridgeCommandDeliveryStatusEnum.CLOSED
        assert entregue.closed_reason == "RESULT_RECEIVED"
        assert entregue.acked_at is None
        session.rollback()
