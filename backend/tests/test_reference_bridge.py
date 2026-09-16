"""The transport, proven against a bridge that is a real process.

`tests/support/reference_bridge.py` runs as its own process: HTTP to the API,
durable local storage, killed at a chosen step with nothing closed carefully,
and started again. Only the acquirer is simulated, as a ledger these tests read
to count charges (§5 of the transport proposal).

What these tests do *not* prove: anything about a real acquirer, a real SDK or
real money. What they do prove is that the path between the server and the
bridge neither loses a charge nor makes a second one when the process dies at
the worst moments, and that not knowing keeps the pinpad taken.

Matrix items covered here: T1 (lost ACK), T4 (death after the SDK answered),
T5 (death before the SDK was called), T6 (result before ACK), I3 (redelivery
repeats the identity). Installations, takeover and rotation (T2, T14, T17–T21)
arrive with §6.6 and §6.7.
"""

import asyncio
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.provider import ProviderTransaction
from app.modules.finance.bridge.models import TefBridgeCommand, TefTerminalOccupancy
from test_bridge_command_delivery import _balcao, _cobrar


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")
REFERENCE_BRIDGE = Path(__file__).resolve().parent / "support" / "reference_bridge.py"
CRASH_EXIT = 86


async def _bridge(balcao, workdir: Path, installation: str, *args: str, timeout: int = 120):
    env = {**os.environ, "DASHEM_BRIDGE_CREDENTIAL": balcao["credential"]}
    command = [
        sys.executable, str(REFERENCE_BRIDGE), "--api", BASE_URL,
        "--terminal", balcao["terminal"]["id"],
        "--store", str(workdir / f"{installation}.sqlite"),
        "--acquirer", str(workdir / "acquirer.sqlite"),
        *args,
    ]
    return await asyncio.to_thread(
        subprocess.run, command, env=env, capture_output=True, text=True, timeout=timeout,
    )


def _charges(workdir: Path, reference: str) -> int:
    ledger = sqlite3.connect(workdir / "acquirer.sqlite")
    try:
        return ledger.execute("SELECT count(*) FROM charges WHERE reference = ?", (reference,)).fetchone()[0]
    finally:
        ledger.close()


def _estado(transaction_id: str):
    with Session(engine) as db:
        set_platform_db_context(db)
        transaction = db.get(ProviderTransaction, uuid.UUID(transaction_id))
        commands = db.exec(select(TefBridgeCommand).where(
            TefBridgeCommand.provider_transaction_id == transaction.id,
        )).all()
        occupancy = db.exec(select(TefTerminalOccupancy).where(
            TefTerminalOccupancy.provider_transaction_id == transaction.id,
        )).first()
        return {
            "status": transaction.status.value,
            "commands": [(c.delivery_status.value, c.attempts, c.acked_at is not None) for c in commands],
            "occupied": occupancy is not None and occupancy.released_at is None,
            "resolution": occupancy.financial_resolution.value if occupancy else None,
        }


@pytest.mark.asyncio
async def test_a_cobranca_vai_e_volta_pelo_bridge_de_referencia(tmp_path):
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        balcao = await _balcao(client, "Referencia")
        primeira, segunda = balcao["parcelas"]
        transacao = (await _cobrar(client, balcao, primeira)).json()["transaction"]["id"]

        rodada = await _bridge(balcao, tmp_path, "loja", "--wait", "5")
        assert rodada.returncode == 0, rodada.stderr

        assert _estado(transacao) == {
            "status": "CONFIRMED", "commands": [("CLOSED", 1, True)],
            "occupied": False, "resolution": "PROVADA_EXECUTADA",
        }
        assert _charges(tmp_path, transacao) == 1
        assert (await _cobrar(client, balcao, segunda)).status_code == 200


@pytest.mark.asyncio
async def test_morrer_depois_do_sdk_consulta_na_volta_e_nao_cobra_de_novo(tmp_path):
    """T4. A chamada saiu e a resposta não foi gravada: a retomada pergunta."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        balcao = await _balcao(client, "DepoisSdk")
        primeira, segunda = balcao["parcelas"]
        transacao = (await _cobrar(client, balcao, primeira)).json()["transaction"]["id"]

        morte = await _bridge(balcao, tmp_path, "loja", "--wait", "5", "--crash-at", "sdk")
        assert morte.returncode == CRASH_EXIT, morte.stderr
        assert _charges(tmp_path, transacao) == 1
        # O dinheiro saiu, o servidor ainda não sabe: maquininha tomada.
        assert _estado(transacao)["status"] == "PROCESSING"
        assert (await _cobrar(client, balcao, segunda)).status_code == 409

        volta = await _bridge(balcao, tmp_path, "loja", "--wait", "1")
        assert volta.returncode == 0, volta.stderr
        assert _charges(tmp_path, transacao) == 1
        estado = _estado(transacao)
        assert estado["status"] == "CONFIRMED" and estado["occupied"] is False
        assert (await _cobrar(client, balcao, segunda)).status_code == 200


@pytest.mark.asyncio
async def test_morrer_antes_do_sdk_fica_incerto_e_segura_a_maquininha(tmp_path):
    """T5. Intenção gravada, nenhuma chamada feita — e de fora não dá para saber."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        balcao = await _balcao(client, "AntesSdk")
        primeira, segunda = balcao["parcelas"]
        transacao = (await _cobrar(client, balcao, primeira)).json()["transaction"]["id"]

        morte = await _bridge(balcao, tmp_path, "loja", "--wait", "5", "--crash-at", "intent")
        assert morte.returncode == CRASH_EXIT, morte.stderr
        volta = await _bridge(balcao, tmp_path, "loja", "--wait", "1")
        assert volta.returncode == 0, volta.stderr

        assert _charges(tmp_path, transacao) == 0
        estado = _estado(transacao)
        assert estado["status"] == "UNKNOWN"
        assert estado["occupied"] is True and estado["resolution"] == "INCERTA"
        ocupada = await _cobrar(client, balcao, segunda)
        assert ocupada.status_code == 409
        assert ocupada.json()["detail"]["provider_transaction_id"] == transacao


@pytest.mark.asyncio
async def test_a_reentrega_repete_a_identidade_e_nao_duplica_a_cobranca(tmp_path):
    """I3. Recebeu, gravou e morreu antes do ACK: o lease vence e o mesmo comando volta."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        balcao = await _balcao(client, "Reentrega")
        transacao = (await _cobrar(client, balcao, balcao["parcelas"][0])).json()["transaction"]["id"]

        morte = await _bridge(balcao, tmp_path, "loja", "--wait", "5", "--crash-at", "received")
        assert morte.returncode == CRASH_EXIT, morte.stderr
        assert _estado(transacao)["commands"] == [("LEASED", 1, False)]

        # Espera o lease vencer dentro da própria espera longa do bridge.
        volta = await _bridge(balcao, tmp_path, "loja", "--wait", "25", "--idle-polls", "3", timeout=150)
        assert volta.returncode == 0, volta.stderr

        assert _estado(transacao) == {
            "status": "CONFIRMED", "commands": [("CLOSED", 2, True)],
            "occupied": False, "resolution": "PROVADA_EXECUTADA",
        }
        assert _charges(tmp_path, transacao) == 1


@pytest.mark.asyncio
async def test_ack_perdido_nao_muda_o_desfecho(tmp_path):
    """T1 e T6. O resultado chega sem ACK nenhum: fecha, e não há o que reentregar."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        balcao = await _balcao(client, "AckPerdido")
        transacao = (await _cobrar(client, balcao, balcao["parcelas"][0])).json()["transaction"]["id"]

        rodada = await _bridge(balcao, tmp_path, "loja", "--wait", "5", "--lose-ack")
        assert rodada.returncode == 0, rodada.stderr
        assert _estado(transacao) == {
            "status": "CONFIRMED", "commands": [("CLOSED", 1, False)],
            "occupied": False, "resolution": "PROVADA_EXECUTADA",
        }
        assert _charges(tmp_path, transacao) == 1


@pytest.mark.asyncio
async def test_controle_uma_retomada_que_cobra_de_novo_aparece_no_livro_razao(tmp_path):
    """A medida quebrada de propósito.

    Se a retomada reexecutasse em vez de consultar, as provas acima teriam de
    ver duas cobranças. Este controle faz exatamente isso, com a chave de
    controle do bridge de referência, e exige que o livro-razão conte duas —
    senão o "uma cobrança" dos outros testes não mediria nada.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        balcao = await _balcao(client, "Controle")
        transacao = (await _cobrar(client, balcao, balcao["parcelas"][0])).json()["transaction"]["id"]

        morte = await _bridge(balcao, tmp_path, "loja", "--wait", "5", "--crash-at", "sdk")
        assert morte.returncode == CRASH_EXIT, morte.stderr
        volta = await _bridge(balcao, tmp_path, "loja", "--wait", "1", "--control-reexecute-on-recovery")
        assert volta.returncode == 0, volta.stderr
        assert _charges(tmp_path, transacao) == 2
