"""A categoria conta o que existe, não o que já foi publicado.

A tela de Categorias mostrava "0 itens" numa categoria com dois produtos
cadastrados. Ela contava juntando duas listas no navegador, e a lista que tinha
era o catálogo **vendável** — a projeção de venda por contexto. Mercadoria
cadastrada e ainda não publicada em nenhum cardápio não entrava na conta.

É o mesmo defeito que o Estoque já corrigiu, pela mesma razão: publicação decide
onde o item pode ser vendido, não se ele existe. Este teste fixa a regra do lado
de cá — quem responde quantos são é quem tem a tabela.
"""

import uuid

from sqlmodel import Session

from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.catalog import Category, ItemTypeEnum, Product
from app.models.identity import Store, Tenant
from app.services import catalog_service


def _cenario(session: Session):
    sufixo = uuid.uuid4().hex[:8]
    tenant = Tenant(name=f"Contagem {sufixo}", slug=f"contagem-{sufixo}")
    session.add(tenant)
    session.flush()
    loja = Store(tenant_id=tenant.id, name="Matriz", code=f"M-{sufixo}")
    session.add(loja)
    session.flush()
    return tenant, loja, sufixo


def test_a_contagem_inclui_produto_que_ninguem_publicou():
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant, loja, sufixo = _cenario(session)
        categoria = Category(tenant_id=tenant.id, name="Materiais", slug=f"materiais-{sufixo}")
        session.add(categoria)
        session.flush()
        # Dois produtos no acervo, nenhum publicado em cardápio nenhum: é
        # exatamente o caso que a tela contava como zero.
        for indice in range(2):
            session.add(Product(
                tenant_id=tenant.id, name=f"Alicate {indice}", sku=f"ALI-{sufixo}-{indice}",
                unit="UN", item_type=ItemTypeEnum.PRODUCT, category_id=categoria.id,
            ))
        session.flush()

        contexto = TenantContext(tenant_id=tenant.id, store_id=loja.id, permissions=frozenset({"catalog.read"}))
        contagens = dict(
            (linha[0].name, linha[1])
            for linha in catalog_service.list_categories_with_usage(session, contexto)
        )
        assert contagens["Materiais"] == 2
        session.rollback()


def test_categoria_vazia_conta_zero_e_aparece_na_lista():
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant, loja, sufixo = _cenario(session)
        session.add(Category(tenant_id=tenant.id, name="Bebidas", slug=f"bebidas-{sufixo}"))
        session.flush()

        contexto = TenantContext(tenant_id=tenant.id, store_id=loja.id, permissions=frozenset({"catalog.read"}))
        contagens = dict(
            (linha[0].name, linha[1])
            for linha in catalog_service.list_categories_with_usage(session, contexto)
        )
        # Zero é uma resposta, não uma ausência: a categoria vazia precisa
        # aparecer para poder ser arquivada.
        assert contagens["Bebidas"] == 0
        session.rollback()


def test_produto_arquivado_nao_impede_arquivar_a_categoria():
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant, loja, sufixo = _cenario(session)
        categoria = Category(tenant_id=tenant.id, name="Descontinuados", slug=f"desc-{sufixo}")
        session.add(categoria)
        session.flush()
        session.add(Product(
            tenant_id=tenant.id, name="Fora de linha", sku=f"OLD-{sufixo}", unit="UN",
            item_type=ItemTypeEnum.PRODUCT, category_id=categoria.id, is_active=False,
        ))
        session.flush()

        contexto = TenantContext(tenant_id=tenant.id, store_id=loja.id, permissions=frozenset({"catalog.read"}))
        contagens = dict(
            (linha[0].name, linha[1])
            for linha in catalog_service.list_categories_with_usage(session, contexto)
        )
        # Quem foi tirado do acervo não pesa na decisão de arquivar a categoria:
        # a tela bloqueia o arquivamento quando a contagem é maior que zero.
        assert contagens["Descontinuados"] == 0
        session.rollback()


def test_a_contagem_nao_atravessa_a_fronteira_do_tenant():
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant_a, loja_a, sufixo_a = _cenario(session)
        tenant_b, _, sufixo_b = _cenario(session)
        categoria_a = Category(tenant_id=tenant_a.id, name="Comum", slug=f"comum-{sufixo_a}")
        categoria_b = Category(tenant_id=tenant_b.id, name="Comum", slug=f"comum-{sufixo_b}")
        session.add_all([categoria_a, categoria_b])
        session.flush()
        session.add(Product(
            tenant_id=tenant_b.id, name="Do vizinho", sku=f"VIZ-{sufixo_b}", unit="UN",
            item_type=ItemTypeEnum.PRODUCT, category_id=categoria_b.id,
        ))
        session.flush()

        contexto = TenantContext(tenant_id=tenant_a.id, store_id=loja_a.id, permissions=frozenset({"catalog.read"}))
        linhas = catalog_service.list_categories_with_usage(session, contexto)
        nomes = {linha[0].name for linha in linhas}
        assert nomes == {"Comum"}
        assert dict((l[0].id, l[1]) for l in linhas)[categoria_a.id] == 0
        session.rollback()
