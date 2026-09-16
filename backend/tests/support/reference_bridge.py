#!/usr/bin/env python
"""Dashem TEF Bridge de referência — um processo de verdade, com adquirente simulado.

Real nesta peça: HTTP pela rede até a API, armazenamento local durável (SQLite
com `synchronous=FULL`, que faz `fsync` a cada commit), um processo que morre no
ponto escolhido e reinicia, e instalações com bancos locais separados.

Simulado, e só isto: o adquirente. Aprovação, recusa, NSU e a memória do que foi
cobrado saem de um livro-razão em SQLite que faz o papel do provedor, e que os
testes leem para contar cobranças. Nada aqui diz coisa alguma sobre dinheiro
real (§5 da proposta de transporte).

A sequência é a de §3.3, e cada passo durável vem antes do seguinte:

1. recebimento do comando, gravado;
2. intenção de acionar o SDK, com a referência exata da chamada, gravada;
3. chamada ao SDK (aqui, ao adquirente simulado);
4. resultado devolvido, gravado;
5. relato ao servidor.

Na retomada, intenção sem resultado **nunca reexecuta** (I5): consulta o
adquirente pela referência gravada no passo 2 e relata o que ele disser — ou
`UNKNOWN`, se ele não souber, e aí a maquininha segue ocupada. Comando repetido
com a mesma identidade é deduplicado aqui, antes de qualquer SDK (I3).

`--crash-at` mata o processo com `os._exit` logo depois do passo nomeado, sem
fechar nada com cuidado — é o desligamento que importa provar.

Não toca produção: fala com a API indicada por `--api`.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import httpx


CRASH_POINTS = ("received", "intent", "sdk", "result")
CRASH_EXIT = 86


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    return connection


class LocalStore:
    """A memória desta instalação. Outra instalação tem a sua, e não enxerga esta."""

    def __init__(self, path: Path) -> None:
        self.db = _connect(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS installation (id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS received (
                command_id TEXT PRIMARY KEY, command_type TEXT NOT NULL,
                provider_transaction_id TEXT NOT NULL, epoch INTEGER NOT NULL,
                payload TEXT NOT NULL, received_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS intents (
                command_id TEXT PRIMARY KEY, reference TEXT NOT NULL, written_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS results (
                command_id TEXT PRIMARY KEY, body TEXT NOT NULL, written_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reports (command_id TEXT PRIMARY KEY, reported_at REAL NOT NULL);
        """)
        if self.db.execute("SELECT count(*) FROM installation").fetchone()[0] == 0:
            self.db.execute("INSERT INTO installation VALUES (?)", (str(uuid.uuid4()),))

    def installation_id(self) -> str:
        return self.db.execute("SELECT id FROM installation").fetchone()[0]

    def receive(self, command: dict) -> bool:
        """Grava o recebimento. Devolve False se esta identidade já tinha chegado."""
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO received VALUES (?, ?, ?, ?, ?, ?)",
            (command["id"], command["command_type"], command["provider_transaction_id"],
             command["installation_epoch"], json.dumps(command["payload"]), time.time()),
        )
        return cursor.rowcount == 1

    def intent(self, command_id: str):
        row = self.db.execute("SELECT reference FROM intents WHERE command_id = ?", (command_id,)).fetchone()
        return row[0] if row else None

    def write_intent(self, command_id: str, reference: str) -> None:
        self.db.execute("INSERT INTO intents VALUES (?, ?, ?)", (command_id, reference, time.time()))

    def result(self, command_id: str):
        row = self.db.execute("SELECT body FROM results WHERE command_id = ?", (command_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def write_result(self, command_id: str, body: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO results VALUES (?, ?, ?)", (command_id, json.dumps(body), time.time()))

    def mark_reported(self, command_id: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO reports VALUES (?, ?)", (command_id, time.time()))

    def pending_recovery(self) -> list[tuple[str, dict]]:
        """O que ficou pela metade: intenção sem relato, com ou sem resultado."""
        rows = self.db.execute("""
            SELECT r.command_id, r.command_type, r.provider_transaction_id, r.epoch, r.payload
              FROM received r
              JOIN intents i ON i.command_id = r.command_id
         LEFT JOIN reports p ON p.command_id = r.command_id
             WHERE p.command_id IS NULL
             ORDER BY r.received_at
        """).fetchall()
        return [(row[0], {
            "id": row[0], "command_type": row[1], "provider_transaction_id": row[2],
            "installation_epoch": row[3], "payload": json.loads(row[4]),
        }) for row in rows]


class SimulatedAcquirer:
    """O papel do provedor, e o único ponto simulado.

    `deduplicates` é a dependência D1 da proposta: com ela, a mesma referência
    não vira segunda cobrança; sem ela, vira — e o livro-razão mostra.
    """

    def __init__(self, path: Path, *, outcome: str, deduplicates: bool) -> None:
        self.db = _connect(path)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS charges (
                reference TEXT NOT NULL, amount TEXT NOT NULL, status TEXT NOT NULL,
                nsu TEXT NOT NULL, charged_at REAL NOT NULL
            )
        """)
        self.outcome = outcome
        self.deduplicates = deduplicates

    def charge(self, reference: str, amount: str) -> dict:
        if self.deduplicates:
            known = self.query(reference)
            if known is not None:
                return known
        nsu = f"{int(time.time() * 1000) % 10**9:09d}"
        self.db.execute(
            "INSERT INTO charges VALUES (?, ?, ?, ?, ?)",
            (reference, amount, self.outcome, nsu, time.time()),
        )
        return {"status": self.outcome, "nsu": nsu, "reference": reference}

    def query(self, reference: str):
        row = self.db.execute(
            "SELECT status, nsu FROM charges WHERE reference = ? ORDER BY charged_at LIMIT 1", (reference,),
        ).fetchone()
        return {"status": row[0], "nsu": row[1], "reference": reference} if row else None


class ReferenceBridge:
    def __init__(self, *, api: str, terminal_id: str, credential: str, store: LocalStore,
                 acquirer: SimulatedAcquirer, crash_at: str | None, lose_ack: bool,
                 control_reexecute: bool = False) -> None:
        self.base = f"{api.rstrip('/')}/api/v1/providers/bridge/terminals/{terminal_id}"
        self.client = httpx.Client(headers={"X-Bridge-Credential": credential}, timeout=40)
        self.store = store
        self.acquirer = acquirer
        self.crash_at = crash_at
        self.lose_ack = lose_ack
        self.control_reexecute = control_reexecute

    def _crash_after(self, point: str) -> None:
        if self.crash_at == point:
            sys.stdout.flush()
            os._exit(CRASH_EXIT)

    def _report(self, command_id: str, body: dict) -> None:
        response = self.client.post(f"{self.base}/commands/{command_id}/result", json=body)
        response.raise_for_status()
        self.store.mark_reported(command_id)

    @staticmethod
    def _body(answer: dict | None) -> dict:
        if answer is None:
            # O adquirente não sabe dizer. Não é recusa: é não saber.
            return {"status": "UNKNOWN", "failure_code": "ACQUIRER_HAS_NO_RECORD"}
        body = {"status": answer["status"], "external_transaction_id": answer["reference"]}
        if answer["status"] == "CONFIRMED":
            body.update(nsu=answer["nsu"], authorization_code="REF001", acquirer="SIMULADO")
        if answer["status"] == "FAILED":
            body.update(failure_code="DECLINED", failure_reason="Recusa simulada.")
        return body

    def recover(self) -> int:
        """Retomada: o que tem intenção e não foi relatado. Nunca reexecuta."""
        handled = 0
        for command_id, command in self.store.pending_recovery():
            body = self.store.result(command_id)
            if body is None:
                reference = self.store.intent(command_id)
                if self.control_reexecute:
                    # Só para o controle dos testes: o erro que a retomada existe para não cometer.
                    answer = self.acquirer.charge(reference, command["payload"]["amount"])
                else:
                    answer = self.acquirer.query(reference)
                body = self._body(answer)
                self.store.write_result(command_id, body)
            self._report(command_id, body)
            handled += 1
        return handled

    def handle(self, command: dict) -> None:
        command_id = command["id"]
        self.store.receive(command)
        self._crash_after("received")
        if not self.lose_ack:
            self.client.post(f"{self.base}/commands/{command_id}/ack").raise_for_status()
        if command["command_type"] != "START":
            return
        body = self.store.result(command_id)
        if body is not None:
            # Já respondido: a reentrega só repete o relato.
            self._report(command_id, body)
            return
        reference = self.store.intent(command_id)
        if reference is not None:
            # Intenção sem resultado: a chamada pode ter saído. Consulta, não cobra.
            body = self._body(self.acquirer.query(reference))
            self.store.write_result(command_id, body)
            self._report(command_id, body)
            return
        reference = command["provider_transaction_id"]
        self.store.write_intent(command_id, reference)
        self._crash_after("intent")
        answer = self.acquirer.charge(reference, command["payload"]["amount"])
        self._crash_after("sdk")
        body = self._body(answer)
        self.store.write_result(command_id, body)
        self._crash_after("result")
        self._report(command_id, body)

    def run(self, *, wait: int, max_commands: int, idle_polls: int) -> int:
        handled = self.recover()
        idle = 0
        while handled < max_commands and idle < idle_polls:
            response = self.client.get(f"{self.base}/commands", params={"wait": wait})
            if response.status_code == 204:
                idle += 1
                continue
            response.raise_for_status()
            idle = 0
            self.handle(response.json())
            handled += 1
        return handled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--api", required=True)
    parser.add_argument("--terminal", required=True)
    parser.add_argument("--credential-env", default="DASHEM_BRIDGE_CREDENTIAL",
                        help="variável de ambiente com a credencial; nunca na linha de comando")
    parser.add_argument("--store", required=True, type=Path, help="banco local desta instalação")
    parser.add_argument("--acquirer", required=True, type=Path, help="livro-razão do adquirente simulado")
    parser.add_argument("--outcome", default="CONFIRMED", choices=("CONFIRMED", "FAILED"))
    parser.add_argument("--acquirer-deduplicates", action="store_true")
    parser.add_argument("--crash-at", choices=CRASH_POINTS)
    parser.add_argument("--lose-ack", action="store_true")
    parser.add_argument("--wait", type=int, default=25)
    parser.add_argument("--max-commands", type=int, default=1)
    parser.add_argument("--idle-polls", type=int, default=1)
    parser.add_argument("--control-reexecute-on-recovery", action="store_true",
                        help="controle de teste: a retomada cobra de novo em vez de consultar")
    args = parser.parse_args(argv)
    credential = os.environ.get(args.credential_env)
    if not credential:
        parser.error(f"defina {args.credential_env} com a credencial do terminal")
    bridge = ReferenceBridge(
        api=args.api, terminal_id=args.terminal, credential=credential,
        store=LocalStore(args.store),
        acquirer=SimulatedAcquirer(args.acquirer, outcome=args.outcome, deduplicates=args.acquirer_deduplicates),
        crash_at=args.crash_at, lose_ack=args.lose_ack,
        control_reexecute=args.control_reexecute_on_recovery,
    )
    handled = bridge.run(wait=args.wait, max_commands=args.max_commands, idle_polls=args.idle_polls)
    print(json.dumps({"handled": handled, "installation_id": bridge.store.installation_id()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
