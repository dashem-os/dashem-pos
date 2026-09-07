#!/usr/bin/env python
"""O conteúdo real da homologação, num banco onde é seguro errar.

O portão de apresentação não se prova com build nem com medida de geometria:
prova-se percorrendo a tela com o que a operação tem de verdade — nome comprido,
mercadoria sem estoque, mínimo não definido, serviço que não controla estoque.
Este semeador reproduz o acervo do `Tenant de Homologação` (lido em modo somente
leitura do banco publicado, sem escrever nele) e acrescenta os nomes mais longos
que existem no acervo do sistema, porque é neles que a coluna quebra.

Ele não toca produção. Roda contra o `DATABASE_URL` local e imprime o que a
travessia precisa: tenant, loja e um token de gestão.
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
from app.core.tenancy import set_platform_db_context
from app.models.assortment import (
    Assortment, AssortmentProduct, AssortmentScope, SalesContextEnum,
)
from app.models.catalog import ItemTypeEnum, InventoryBalance, Product, ProductPrice
from app.models.identity import (
    AuthIdentity, Membership, MembershipStatusEnum, RoleEnum, Store, Tenant,
    TenantStatusEnum, User,
)
from app.models.platform import TenantCapability

CAPABILITIES = (
    "barcode_scanning", "cash_management", "catalog", "combos", "counter_order",
    "customer", "delivery_orders", "fiscal_nfce", "high_speed_checkout",
    "inventory", "kitchen_routing", "modifiers", "payments", "receivables",
    "supervisor_override", "table_service",
)

# nome, sku, unidade, tipo, preço, saldo, mínimo, controla estoque
CATALOGO = (
    ("Coca-Cola Lata", "COC-051", "UN", ItemTypeEnum.PRODUCT, "8.00", "10", "0", True),
    ("Coca-Cola Sem Açucar 600ml", "COC-050", "UN", ItemTypeEnum.PRODUCT, "10.00", "9", "0", True),
    ("Hambúrguer Artesanal Bacon", "HAB-01", "UN", ItemTypeEnum.PRODUCT, "32.00", "15", "12", True),
    # Os dois nomes mais longos do acervo do sistema: é onde a coluna aperta.
    ("Alicate Decapador e Crimpador Automático", "ALI-DEC-01", "UN", ItemTypeEnum.PRODUCT, "89.90", "3", "5", True),
    ("Canaleta 20x10mm com Fita Dupla Face 2m", "CAN-2010", "UN", ItemTypeEnum.PRODUCT, "24.50", "0", "6", True),
    # Serviço não tem prateleira, e a tela precisa dizer isso com palavra.
    ("Taxa de entrega", "TX-ENT", "UN", ItemTypeEnum.SERVICE, "7.00", "0", "0", False),
)


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


def seed(output: Path) -> None:
    sufixo = uuid.uuid4().hex[:6]
    subject = str(uuid.uuid4())
    email = f"gestora-{sufixo}@homologacao.test"

    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name="Tenant de Homologação", slug=f"homologacao-{sufixo}",
                        status=TenantStatusEnum.TRIAL)
        # Sem isto o aplicativo abre no primeiro acesso e pede senha: a
        # travessia precisa entrar na gestão, não na cerimônia de acesso.
        gestora = User(email=email, full_name="Marcela Almeida",
                       password_setup_completed_at=datetime.now(timezone.utc))
        session.add_all([tenant, gestora])
        session.flush()
        session.add(AuthIdentity(user_id=gestora.id, provider="supabase",
                                 provider_subject=subject, provider_email=email,
                                 email_verified=True))
        session.add(Membership(user_id=gestora.id, tenant_id=tenant.id,
                               role=RoleEnum.TENANT_OWNER, status=MembershipStatusEnum.ACTIVE))
        session.add_all([TenantCapability(tenant_id=tenant.id, key=chave, enabled=True)
                         for chave in CAPABILITIES])
        loja = Store(tenant_id=tenant.id, name="Matriz Homologação",
                     code=f"MTZ-{sufixo}", is_headquarters=True)
        session.add(loja)
        session.flush()

        produtos: dict[str, uuid.UUID] = {}
        for nome, sku, unidade, tipo, preco, saldo, minimo, controla in CATALOGO:
            produto = Product(tenant_id=tenant.id, name=nome, sku=sku, unit=unidade,
                              item_type=tipo, tracks_inventory=controla)
            session.add(produto)
            session.flush()
            produtos[sku] = produto.id
            session.add(ProductPrice(tenant_id=tenant.id, store_id=None, product_id=produto.id,
                                     sale_price=Decimal(preco), cost_price=Decimal(preco) / 2))
            if controla:
                session.add(InventoryBalance(tenant_id=tenant.id, store_id=loja.id,
                                             product_id=produto.id, quantity=Decimal(saldo),
                                             minimum_stock=Decimal(minimo), version=1))

        cardapio = Assortment(tenant_id=tenant.id, code="CARDÁPIO-LOJA",
                              name="Cardápio Principal da Loja", version=4,
                              description="O que a loja vende no balcão e na entrega.")
        bebidas = Assortment(tenant_id=tenant.id, code="BEBIDAS-GELADAS",
                             name="Bebidas Geladas", version=1)
        session.add_all([cardapio, bebidas])
        session.flush()
        for contexto in (SalesContextEnum.COUNTER, SalesContextEnum.TAKEAWAY,
                         SalesContextEnum.DELIVERY, SalesContextEnum.TABLE):
            session.add(AssortmentScope(tenant_id=tenant.id, assortment_id=cardapio.id,
                                        store_id=loja.id, sales_context=contexto))
        for ordem, sku in enumerate(("COC-051", "COC-050", "HAB-01")):
            session.add(AssortmentProduct(tenant_id=tenant.id, assortment_id=cardapio.id,
                                          product_id=produtos[sku], sort_order=ordem * 10))
        for ordem, sku in enumerate(("COC-051", "COC-050")):
            session.add(AssortmentProduct(tenant_id=tenant.id, assortment_id=bebidas.id,
                                          product_id=produtos[sku], sort_order=ordem * 10))
        session.commit()

        fixture = {
            "tenant_id": str(tenant.id), "tenant_name": tenant.name,
            "store_id": str(loja.id), "store_name": loja.name,
            "manager_email": email, "manager_token": _token(subject, email),
            "products": {sku: str(pid) for sku, pid in produtos.items()},
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(fixture, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"travessia semeada: {tenant.name} / {loja.name} · {len(CATALOGO)} produtos")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    seed(parser.parse_args().output)
