#!/usr/bin/env python
"""Duas estações no mesmo balcão, para o cenário obrigatório ser percorrido.

O que se prova aqui não cabe em teste unitário: a operadora abre uma venda numa
estação, a supervisora abre outra na estação ao lado, e as duas disputam a mesma
prateleira. Dezesseis unidades, dez prometidas à primeira venda, sete recusadas
na segunda, o cancelamento autorizado por quem tem autoridade, e as sete
liberadas em seguida.

A operadora é CAIXA: depois da 089 ela não cancela sozinha. A supervisora tem
uma credencial operacional (código e PIN) para digitar no terminal da operadora
— é essa a chegada ao balcão que o diálogo de autorização representa.

Não toca produção: roda contra o `DATABASE_URL` local.
"""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import jwt
from sqlmodel import Session

from app.core.config import settings
from app.core.database import engine
from app.core.context import TenantContext
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.assortment import (
    Assortment, AssortmentProduct, AssortmentScope, SalesContextEnum,
)
from app.models.catalog import ItemTypeEnum, InventoryBalance, Product, ProductPrice
from app.models.device import OperationalDevice, OperationalDeviceTypeEnum
from app.models.identity import (
    AuthIdentity, Employee, EmployeeStatusEnum, Membership, MembershipStatusEnum,
    OperationalCredential, Register, RoleEnum, Store, Tenant, TenantStatusEnum, User,
)
from app.models.platform import TenantCapability
from app.services import operational_access_service

CAPABILITIES = (
    "barcode_scanning", "cash_management", "catalog", "counter_order", "customer",
    "fiscal_nfce", "high_speed_checkout", "inventory", "payments", "receivables",
    "supervisor_override", "table_service",
)

# O produto do cenário: por padrão dezesseis na prateleira, e é sobre ele que as
# duas estações vão discordar. `--saldo 1` monta o cenário da **última unidade**,
# em que as duas querem a mesma peça e só uma pode levar.
CATALOGO = (
    ("Coca-Cola Lata", "COC-051", "8.00", "16", "0"),
    ("Hambúrguer Artesanal Bacon", "HAB-01", "32.00", "15", "12"),
)
PRODUTO_DISPUTADO = "COC-051"

# `--volume N` acrescenta N produtos ao acervo, para medir busca e grade sob
# carga. Os nomes se espalham pelo alfabeto de propósito: quem lista ordenado
# por nome e corta em algum número mostra o começo do alfabeto e esconde o fim.
FAMILIAS = (
    "Arroz", "Biscoito", "Café", "Detergente", "Erva-mate", "Farinha",
    "Goiabada", "Hambúrguer", "Iogurte", "Jujuba", "Ketchup", "Leite",
    "Macarrão", "Néctar", "Óleo", "Pão", "Queijo", "Refrigerante",
    "Sabonete", "Tempero", "Uva-passa", "Vinagre",
)
#: O produto do fim do alfabeto. Ele existe, é vendável, e é o que qualquer
#: corte silencioso vai deixar de fora — por isso a travessia procura por ele.
PRODUTO_DO_FIM = ("Zimbro Desidratado 5kg", "ZIM-0001", "74.90")

CODIGO_SUPERVISORA = "SUP-01"
PIN_SUPERVISORA = "4826"
CODIGO_OPERADORA = "CX-01"
PIN_OPERADORA = "5731"


def _token(subject: str, email: str) -> str:
    if not settings.AUTH_TEST_SECRET:
        raise RuntimeError("AUTH_TEST_SECRET é obrigatório para a travessia.")
    agora = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": subject, "email": email, "aud": settings.SUPABASE_JWT_AUDIENCE,
            "iat": agora, "exp": agora + timedelta(hours=8), "aal": "aal1",
            "app_metadata": {"provider": "email"},
        },
        settings.AUTH_TEST_SECRET, algorithm="HS256",
    )


def _catalogo_volumoso(session: Session, tenant, loja, quantos: int) -> dict[str, uuid.UUID]:
    """Acervo grande, com nomes espalhados pelo alfabeto e um produto no fim dele.

    Não é enfeite: a medida de "catálogo volumoso" precisa de um produto que
    esteja comprovadamente **depois** de qualquer corte por ordem de nome.
    """
    criados: dict[str, uuid.UUID] = {}
    for indice in range(quantos):
        familia = FAMILIAS[indice % len(FAMILIAS)]
        numero = indice // len(FAMILIAS) + 1
        nome = f"{familia} Tipo {numero:03d}"
        sku = f"VOL-{indice + 1:05d}"
        preco = Decimal("3.50") + Decimal(indice % 40)
        produto = Product(tenant_id=tenant.id, name=nome, sku=sku, unit="UN",
                          item_type=ItemTypeEnum.PRODUCT, tracks_inventory=True)
        session.add(produto)
        session.flush()
        criados[sku] = produto.id
        session.add(ProductPrice(tenant_id=tenant.id, store_id=loja.id, product_id=produto.id,
                                 sale_price=preco, cost_price=preco / 2))
        session.add(InventoryBalance(tenant_id=tenant.id, store_id=loja.id,
                                     product_id=produto.id, quantity=Decimal("40"),
                                     minimum_stock=Decimal("0"), version=1))

    nome_fim, sku_fim, preco_fim = PRODUTO_DO_FIM
    produto = Product(tenant_id=tenant.id, name=nome_fim, sku=sku_fim, unit="UN",
                      item_type=ItemTypeEnum.PRODUCT, tracks_inventory=True)
    session.add(produto)
    session.flush()
    criados[sku_fim] = produto.id
    session.add(ProductPrice(tenant_id=tenant.id, store_id=loja.id, product_id=produto.id,
                             sale_price=Decimal(preco_fim), cost_price=Decimal(preco_fim) / 2))
    session.add(InventoryBalance(tenant_id=tenant.id, store_id=loja.id,
                                 product_id=produto.id, quantity=Decimal("12"),
                                 minimum_stock=Decimal("0"), version=1))
    return criados


def _pessoa(session: Session, tenant, loja, *, nome: str, papel: RoleEnum, apelido: str, sufixo: str):
    """Alguém que entra pelo aplicativo, com vínculo na unidade."""
    subject = str(uuid.uuid4())
    email = f"{apelido}-{sufixo}@homologacao.test"
    usuario = User(email=email, full_name=nome,
                   password_setup_completed_at=datetime.now(timezone.utc))
    session.add(usuario)
    session.flush()
    session.add(AuthIdentity(user_id=usuario.id, provider="supabase", provider_subject=subject,
                             provider_email=email, email_verified=True))
    # Quem assume terminal tem vínculo preso à unidade: é isso que a entrada
    # operacional confere (`membership.store_id != device.store_id` recusa).
    # Quem entra pela Gestão tem vínculo do tenant, porque no primeiro acesso
    # ainda não há janela de tenant aberta para a RLS enxergar o outro.
    da_unidade = papel in {RoleEnum.SUPERVISOR, RoleEnum.CASHIER, RoleEnum.OPERATOR}
    vinculo = Membership(user_id=usuario.id, tenant_id=tenant.id,
                         store_id=loja.id if da_unidade else None,
                         role=papel, status=MembershipStatusEnum.ACTIVE)
    session.add(vinculo)
    session.flush()
    return usuario, vinculo, subject, email


def seed(output: Path, saldo_disputado: str | None = None, volume: int = 0) -> None:
    sufixo = uuid.uuid4().hex[:6]

    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name="Balcão de Homologação", slug=f"balcao-{sufixo}",
                        status=TenantStatusEnum.TRIAL)
        session.add(tenant)
        session.flush()
        session.add_all([TenantCapability(tenant_id=tenant.id, key=chave, enabled=True)
                         for chave in CAPABILITIES])
        loja = Store(tenant_id=tenant.id, name="Matriz Homologação",
                     code=f"MTZ-{sufixo}", is_headquarters=True)
        session.add(loja)
        session.flush()

        # Duas estações de verdade: cada uma com o próprio caixa e terminal.
        estacoes = []
        for numero in (1, 2):
            registradora = Register(tenant_id=tenant.id, store_id=loja.id,
                                    name=f"Caixa 0{numero}", code=f"CX{numero}-{sufixo}")
            session.add(registradora)
            session.flush()
            terminal = OperationalDevice(
                tenant_id=tenant.id, store_id=loja.id, code=f"POS{numero}-{sufixo}",
                name=f"Terminal 0{numero}", device_type=OperationalDeviceTypeEnum.POS,
                register_id=registradora.id,
            )
            session.add(terminal)
            session.flush()
            estacoes.append((registradora, terminal))
        caixa = estacoes[0][0]

        gestora, _vinculo_gestora, sub_gestora, email_gestora = _pessoa(
            session, tenant, loja, nome="Marcela Almeida", papel=RoleEnum.TENANT_OWNER,
            apelido="gestora", sufixo=sufixo,
        )
        operadora, vinculo_op, sub_op, email_op = _pessoa(
            session, tenant, loja, nome="Joana Ribeiro", papel=RoleEnum.CASHIER,
            apelido="operadora", sufixo=sufixo,
        )
        supervisora, vinculo_sup, sub_sup, email_sup = _pessoa(
            session, tenant, loja, nome="Marta Nogueira", papel=RoleEnum.SUPERVISOR,
            apelido="supervisora", sufixo=sufixo,
        )

        # A credencial que a supervisora digita no terminal da operadora.
        empregada = Employee(
            tenant_id=tenant.id, user_id=supervisora.id, home_store_id=loja.id,
            employee_number=CODIGO_SUPERVISORA, full_name="Marta Nogueira",
            status=EmployeeStatusEnum.ACTIVE,
        )
        session.add(empregada)
        session.flush()
        salt, pin_hash, iteracoes = operational_access_service.new_pin_secret(PIN_SUPERVISORA)
        session.add(OperationalCredential(
            tenant_id=tenant.id, store_id=loja.id, user_id=supervisora.id,
            membership_id=vinculo_sup.id, employee_id=empregada.id,
            employee_code=CODIGO_SUPERVISORA, pin_salt=salt, pin_hash=pin_hash,
            pin_iterations=iteracoes, pin_activated_at=datetime.utcnow(),
        ))

        empregado_caixa = Employee(
            tenant_id=tenant.id, user_id=operadora.id, home_store_id=loja.id,
            employee_number=CODIGO_OPERADORA, full_name="Joana Ribeiro",
            status=EmployeeStatusEnum.ACTIVE,
        )
        session.add(empregado_caixa)
        session.flush()
        salt_op, hash_op, iter_op = operational_access_service.new_pin_secret(PIN_OPERADORA)
        session.add(OperationalCredential(
            tenant_id=tenant.id, store_id=loja.id, user_id=operadora.id,
            membership_id=vinculo_op.id, employee_id=empregado_caixa.id,
            employee_code=CODIGO_OPERADORA, pin_salt=salt_op, pin_hash=hash_op,
            pin_iterations=iter_op, pin_activated_at=datetime.utcnow(),
        ))

        produtos: dict[str, uuid.UUID] = {}
        for nome, sku, preco, saldo, minimo in CATALOGO:
            produto = Product(tenant_id=tenant.id, name=nome, sku=sku, unit="UN",
                              item_type=ItemTypeEnum.PRODUCT, tracks_inventory=True)
            session.add(produto)
            session.flush()
            produtos[sku] = produto.id
            session.add(ProductPrice(tenant_id=tenant.id, store_id=loja.id, product_id=produto.id,
                                     sale_price=Decimal(preco), cost_price=Decimal(preco) / 2))
            # O saldo do produto disputado pode ser trocado pela linha de
            # comando: é a diferença entre o cenário de autoridade (dezesseis,
            # com sete recusadas) e o da última unidade (uma só, e duas pessoas
            # a querendo ao mesmo tempo).
            quantidade = (
                saldo_disputado if (saldo_disputado and sku == PRODUTO_DISPUTADO) else saldo
            )
            session.add(InventoryBalance(tenant_id=tenant.id, store_id=loja.id,
                                         product_id=produto.id, quantity=Decimal(quantidade),
                                         minimum_stock=Decimal(minimo), version=1))

        # O acervo volumoso entra antes do cardápio para ser vendável junto com
        # o resto: a grade do PDV lê o sortimento, não a tabela de produtos.
        volumosos = _catalogo_volumoso(session, tenant, loja, volume) if volume else {}
        produtos.update(volumosos)

        cardapio = Assortment(tenant_id=tenant.id, code="CARDAPIO-LOJA",
                              name="Cardápio Principal da Loja", version=1,
                              description="O que a loja vende no balcão.")
        session.add(cardapio)
        session.flush()
        for contexto in (SalesContextEnum.COUNTER, SalesContextEnum.TAKEAWAY):
            session.add(AssortmentScope(tenant_id=tenant.id, assortment_id=cardapio.id,
                                        store_id=loja.id, sales_context=contexto))
        for ordem, sku in enumerate(produtos):
            session.add(AssortmentProduct(tenant_id=tenant.id, assortment_id=cardapio.id,
                                          product_id=produtos[sku], sort_order=ordem * 10))
        session.commit()

        # Autorizar o terminal é ato de quem responde pela unidade, feito uma
        # vez na abertura. O que se homologa depois é a entrada de cada pessoa.
        set_tenant_db_context(session, tenant.id, loja.id, gestora.id)
        contexto_gestora = TenantContext(
            tenant_id=tenant.id, store_id=loja.id, user_id=gestora.id,
            role=RoleEnum.TENANT_OWNER,
        )
        terminais = []
        for _registradora, terminal in estacoes:
            autorizacao = operational_access_service.authorize_terminal(
                session, contexto_gestora, terminal.id,
            )
            terminais.append(autorizacao["terminal_token"])
        session.commit()

        fixture = {
            "tenant_id": str(tenant.id), "store_id": str(loja.id),
            "register_id": str(caixa.id),
            "operator": {"email": email_op, "token": _token(sub_op, email_op),
                         "name": "Joana Ribeiro", "role": "CASHIER",
                         "employee_code": CODIGO_OPERADORA, "pin": PIN_OPERADORA,
                         "terminal_token": terminais[0]},
            "supervisor": {"email": email_sup, "token": _token(sub_sup, email_sup),
                           "name": "Marta Nogueira", "role": "SUPERVISOR",
                           "employee_code": CODIGO_SUPERVISORA, "pin": PIN_SUPERVISORA,
                           "terminal_token": terminais[1]},
            "products": {sku: str(pid) for sku, pid in produtos.items()},
            # A gestora entra pela Gestão e é ela quem concede e retira
            # autoridade. O vínculo da operadora vem junto porque é nele que a
            # marcação é escrita.
            "manager": {"email": email_gestora, "token": _token(sub_gestora, email_gestora),
                        "name": "Marcela Almeida", "role": "TENANT_OWNER"},
            "operator_membership_id": str(vinculo_op.id),
            "volume": {
                "quantos": len(volumosos),
                "produto_do_fim": {"nome": PRODUTO_DO_FIM[0], "sku": PRODUTO_DO_FIM[1],
                                   "product_id": str(volumosos[PRODUTO_DO_FIM[1]])}
                if volumosos else None,
            },
            "disputado": {"sku": PRODUTO_DISPUTADO,
                          "product_id": str(produtos[PRODUTO_DISPUTADO]),
                          "saldo": saldo_disputado or "16"},
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(fixture, indent=2, ensure_ascii=False), encoding="utf-8")
    na_prateleira = saldo_disputado or "16"
    quantos = fixture["volume"]["quantos"]
    extra = f"; acervo com {quantos + len(CATALOGO)} produtos vendáveis" if quantos else ""
    print("duas estações semeadas: operadora CAIXA e supervisora com código "
          f"{CODIGO_SUPERVISORA}; Coca-Cola com {na_prateleira} na prateleira{extra}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--saldo", default=None,
        help="Saldo do produto disputado. Use 1 para o cenário da última unidade.",
    )
    parser.add_argument(
        "--volume", default=0, type=int,
        help="Quantos produtos extras semear, para o cenário de catálogo volumoso.",
    )
    argumentos = parser.parse_args()
    seed(argumentos.output, saldo_disputado=argumentos.saldo, volume=argumentos.volume)
