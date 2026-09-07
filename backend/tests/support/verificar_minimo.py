#!/usr/bin/env python
"""O que a tela promete, conferido fora dela.

Configurar o mínimo não pode mexer no saldo nem criar movimento. A tela diz
isso; este roteiro confere no banco, antes e depois da travessia, porque
promessa de tela se verifica no dado.

Uso: `--antes arquivo.json` grava o retrato; `--depois arquivo.json` compara.
Roda contra o `DATABASE_URL` local. Não toca produção.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from app.core.database import engine
from app.core.tenancy import set_platform_db_context

CONSULTA = """
    select p.sku, b.quantity, b.minimum_stock, b.version,
           (select count(*) from inventory_movements m where m.product_id = p.id) as movimentos
    from products p
    join inventory_balances b on b.product_id = p.id
    order by p.sku
"""


def retrato() -> dict:
    with Session(engine) as session:
        set_platform_db_context(session)
        linhas = session.exec(text(CONSULTA)).all()
    return {
        linha.sku: {
            "saldo": str(linha.quantity),
            "minimo": str(linha.minimum_stock),
            "versao": linha.version,
            "movimentos": linha.movimentos,
        }
        for linha in linhas
    }


def comparar(antes: dict, depois: dict) -> int:
    problemas = []
    for sku, atual in depois.items():
        anterior = antes.get(sku)
        if anterior is None:
            problemas.append(f"{sku}: apareceu depois da travessia")
            continue
        if atual["saldo"] != anterior["saldo"]:
            problemas.append(f"{sku}: saldo mudou de {anterior['saldo']} para {atual['saldo']}")
        if atual["movimentos"] != anterior["movimentos"]:
            problemas.append(
                f"{sku}: movimentos passaram de {anterior['movimentos']} para {atual['movimentos']}"
            )
        if atual["versao"] != anterior["versao"]:
            problemas.append(f"{sku}: versão do saldo mudou de {anterior['versao']} para {atual['versao']}")
        if atual["minimo"] != anterior["minimo"]:
            print(f"  {sku}: mínimo {anterior['minimo']} -> {atual['minimo']} (esperado)")

    print()
    for sku, atual in sorted(depois.items()):
        print(f"  {sku:10} saldo={atual['saldo']:>10}  mínimo={atual['minimo']:>10}  "
              f"movimentos={atual['movimentos']}  versão={atual['versao']}")
    print()
    if problemas:
        for problema in problemas:
            print(f"FALHA {problema}")
        return 1
    print("Saldo, contagem de movimentos e versão idênticos: configurar não movimentou.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--antes", type=Path)
    parser.add_argument("--depois", type=Path)
    args = parser.parse_args()

    if args.antes and not args.depois:
        args.antes.write_text(json.dumps(retrato(), indent=2), encoding="utf-8")
        print(f"retrato gravado em {args.antes}")
        raise SystemExit(0)
    if not args.antes or not args.depois:
        raise SystemExit("informe --antes para gravar, ou --antes e --depois para comparar")
    raise SystemExit(comparar(json.loads(args.antes.read_text(encoding="utf-8")), retrato()))
