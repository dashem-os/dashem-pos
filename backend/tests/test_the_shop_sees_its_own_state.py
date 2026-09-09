"""Diagnóstico e acesso assistido: o contrato da UX-12.

Duas metades, e a segunda é a que mudou comportamento de código publicado.
`assisted_support_grants` era pedido pela plataforma e decidido pela plataforma;
o dono dos dados não via, não aprovava e não revogava. Estas provas guardam a
regra nova nos dois sentidos: a plataforma não consegue mais aprovar, e revogar
tem efeito na leitura seguinte.

O acesso vale ou não vale **agora** — a expiração é conferida na hora, não
gravada. Uma coluna "expirado" precisaria de alguém virando linhas quando o
prazo vence, e esse processo não existe.
"""

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta

import httpx
import pytest
from sqlmodel import Session, select

from app.api.v1.endpoints.control import (
    SupportGrantCreate, SupportGrantDecision, control_workspace, decide_support,
    request_support,
)
from app.api.v1.endpoints.diagnostics import registrar_no_historico
from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.core.security import AuthPrincipal
from app.models.identity import AuthIdentity, User
from app.models.platform import (
    AssistedSupportGrant, PlatformMembership, PlatformRoleEnum,
    SupportGrantEventTypeEnum, SupportGrantStatusEnum,
)
from app.models.reliability import AuditEvent

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


def _janela_da_plataforma(session: Session) -> None:
    """A política das tabelas é forçada: sem janela aberta, a linha não existe.

    As rotas abrem a janela sozinhas — `require_platform_role` faz isso. Uma
    sessão crua de teste não faz, e `session.get` devolve `None` sem erro, o que
    parece dado ausente e é política funcionando.
    """
    set_platform_db_context(session, None)


def _plataforma(session: Session) -> tuple[AuthPrincipal, User]:
    """Um usuário da plataforma, como o resto da suíte já monta.

    As rotas de `control` não passam pelo bypass de autenticação do servidor de
    teste: elas exigem vínculo de plataforma e AAL2. Por isso o lado da
    plataforma é exercitado chamando as funções direto, com sessão própria — o
    mesmo padrão de `test_s18_control_completion.py` — enquanto o lado do
    lojista fala HTTP, que é onde o contrato dele vive.
    """
    subject = str(uuid.uuid4())
    user = User(email=f"ux12-{subject}@example.test", full_name="Suporte UX-12")
    session.add(user)
    session.flush()
    session.add(AuthIdentity(
        user_id=user.id, provider="supabase", provider_subject=subject,
        provider_email=user.email, email_verified=True,
    ))
    session.add(PlatformMembership(user_id=user.id, role=PlatformRoleEnum.PLATFORM_OWNER))
    session.commit()
    session.refresh(user)
    principal = AuthPrincipal(
        subject=subject, email=user.email, session_id=str(uuid.uuid4()),
        assurance_level="aal2", claims={"sub": subject, "aal": "aal2"}, provider="email",
    )
    return principal, user


async def _tenant(client: httpx.AsyncClient) -> dict:
    sufixo = uuid.uuid4().hex[:8]
    tenant = (await client.post("/api/v1/identity/tenants", json={
        "name": f"Diagnóstico {sufixo}", "slug": f"diagnostico-{sufixo}",
    })).json()
    loja = (await client.post("/api/v1/identity/stores", json={
        "tenant_id": tenant["id"], "name": "Matriz", "code": f"M-{sufixo}",
    })).json()
    return {"headers": {"X-Tenant-ID": tenant["id"], "X-Store-ID": loja["id"]},
            "tenant": tenant, "loja": loja, "sufixo": sufixo}


def _pedir_acesso(tenant_id: str, segundos: int = 4 * 3600,
                  escopo=("operations",)) -> dict:
    """O pedido continua vindo da plataforma. Só a decisão mudou de lado.

    O `principal` volta junto de propósito: a autorização é **nominal**, e ler
    o workspace com outra pessoa não abre nada. Um ajudante que criasse um
    profissional novo a cada leitura mediria sempre o caso do estranho.
    """
    with Session(engine) as session:
        principal, pessoa = _plataforma(session)
        concessao = request_support(
            uuid.UUID(tenant_id),
            SupportGrantCreate(
                scope=list(escopo),
                reason="Investigar lentidão relatada pelo lojista",
                expires_at=datetime.utcnow() + timedelta(seconds=segundos),
            ),
            principal, session,
        )
        return {
            "id": str(concessao.id), "status": concessao.status.value,
            "principal": principal, "nome": pessoa.full_name, "email": pessoa.email,
        }


def _workspace(tenant_id: str, principal: AuthPrincipal) -> dict:
    """O workspace **na sessão daquela pessoa**. Não existe leitura anônima."""
    with Session(engine) as session:
        return control_workspace(uuid.UUID(tenant_id), principal, session)


# ---------------------------------------------------------------------------
# Parte 1 — está tudo funcionando?
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_o_diagnostico_responde_na_lingua_de_quem_tem_a_loja():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        resposta = await client.get("/api/v1/diagnostics", headers=ctx["headers"])
        assert resposta.status_code == 200, resposta.text
        corpo = resposta.json()

        assert corpo["situacao_geral"] == "SAUDAVEL"
        chaves = {v["chave"] for v in corpo["verificacoes"]}
        assert {"servidor", "dados", "sincronizacao"} <= chaves

        # Nada de jargão: "outbox" e "backlog" são palavras nossas, não dele.
        texto = " ".join(v["resumo"] for v in corpo["verificacoes"]).lower()
        for palavra in ("outbox", "backlog", "aal2", "payload", "queue"):
            assert palavra not in texto, f"a tela do lojista fala '{palavra}'"

        # Toda verificação traz a frase pronta: duas telas não podem redigir a
        # mesma resposta de jeitos diferentes.
        assert all(v["resumo"].strip() for v in corpo["verificacoes"])


@pytest.mark.asyncio
async def test_o_diagnostico_acusa_o_que_esta_parado_para_sincronizar():
    """Silêncio não é saúde, e pendência velha não é normal."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h, loja, sufixo = ctx["headers"], ctx["loja"], ctx["sufixo"]

        # Uma operação real que escreve na fila: lançar uma conta a pagar.
        await client.post("/api/v1/payables", headers={**h, "Idempotency-Key": str(uuid.uuid4())},
                          json={"payee_name": "Fornecedor", "amount": "10.00",
                                "due_on": str(datetime.utcnow().date())})

        corpo = (await client.get("/api/v1/diagnostics", headers=h)).json()
        sincronizacao = next(v for v in corpo["verificacoes"] if v["chave"] == "sincronizacao")
        # Recém-criada, ela ainda não está atrasada — mas está contada.
        assert sincronizacao["detalhes"]["esperando"] >= 1
        assert sincronizacao["detalhes"]["com_falha"] == 0
        assert sincronizacao["situacao"] in ("SAUDAVEL", "ATENCAO")


@pytest.mark.asyncio
async def test_o_aparelho_que_nunca_deu_sinal_nao_conta_como_saudavel():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h, loja, sufixo = ctx["headers"], ctx["loja"], ctx["sufixo"]
        criado = await client.post("/api/v1/devices", headers=h, json={
            "store_id": loja["id"], "code": f"PDV-{sufixo}", "name": "Caixa da frente",
            "device_type": "POS",
        })
        assert criado.status_code in (200, 201), criado.text

        corpo = (await client.get("/api/v1/diagnostics", headers=h)).json()
        assert len(corpo["aparelhos"]) == 1
        aparelho = corpo["aparelhos"][0]
        assert aparelho["nome"] == "Caixa da frente"
        # Nunca visto não é "saudável": é "não verificado".
        assert aparelho["situacao"] == "NAO_VERIFICADO"
        assert aparelho["visto_em"] is None
        # E a situação geral acompanha a pior parte, não a média.
        assert corpo["situacao_geral"] == "NAO_VERIFICADO"


# ---------------------------------------------------------------------------
# Parte 2 — quem entra nos meus dados
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_plataforma_pede_e_nao_aprova():
    """A mudança de comportamento que esta sprint existe para fazer."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        concessao = _pedir_acesso(ctx["tenant"]["id"])
        assert concessao["status"] == "PENDING"

        with Session(engine) as session:
            principal, _ = _plataforma(session)
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as tentativa:
                decide_support(
                    uuid.UUID(concessao["id"]),
                    SupportGrantDecision(
                        status=SupportGrantStatusEnum.APPROVED,
                        reason="Aprovando por conta própria",
                    ),
                    principal, session,
                )
        assert tentativa.value.status_code == 403
        assert "responsável autorizado" in str(tentativa.value.detail)

        # E continua pendente: a tentativa não deixou rastro de aprovação.
        na_loja = (await client.get("/api/v1/diagnostics/acesso-assistido",
                                    headers=ctx["headers"])).json()
        assert [a["situacao"] for a in na_loja] == ["PENDING"]
        assert na_loja[0]["vale_agora"] is False


@pytest.mark.asyncio
async def test_o_lojista_ve_aprova_e_o_acesso_passa_a_valer():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        concessao = _pedir_acesso(ctx["tenant"]["id"])

        # Ele vê o pedido com escopo, motivo e prazo — o que está aprovando.
        lista = (await client.get("/api/v1/diagnostics/acesso-assistido", headers=h)).json()
        assert lista[0]["escopo"] == ["operations"]
        assert "lentidão" in lista[0]["motivo"]
        assert lista[0]["expira_em"]

        aprovado = await client.post(
            f"/api/v1/diagnostics/acesso-assistido/{concessao['id']}/aprovacao",
            headers=h, json={"motivo": "Autorizei por telefone com o suporte"})
        assert aprovado.status_code == 200, aprovado.text
        assert aprovado.json()["situacao"] == "APPROVED"
        assert aprovado.json()["vale_agora"] is True

        # Aprovar duas vezes não é aprovar de novo.
        outra_vez = await client.post(
            f"/api/v1/diagnostics/acesso-assistido/{concessao['id']}/aprovacao",
            headers=h, json={"motivo": "Cliquei sem querer"})
        assert outra_vez.status_code == 409, outra_vez.text


@pytest.mark.asyncio
async def test_sem_aprovacao_do_lojista_a_plataforma_nao_le_a_operacao_dele():
    """A revogação só é efetiva se a autorização governar alguma coisa.

    Hoje o único lugar em que a plataforma lê estado operacional de um tenant é
    o bloco de operações do workspace de controle. Ele passou a ser a porta —
    e é por ela que se prova que aprovar e revogar mudam o mundo, não só a
    linha da tabela.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h, tenant_id = ctx["headers"], ctx["tenant"]["id"]

        concessao = _pedir_acesso(tenant_id)

        # Pedido sozinho não abre nada — nem para quem pediu.
        antes = _workspace(tenant_id, concessao["principal"])
        assert antes["operations"]["acesso"] == "SEM_AUTORIZACAO"
        assert "backlog" not in antes["operations"]
        await client.post(f"/api/v1/diagnostics/acesso-assistido/{concessao['id']}/aprovacao",
                          headers=h, json={"motivo": "Autorizei o suporte"})
        depois = _workspace(tenant_id, concessao["principal"])
        assert depois["operations"]["acesso"] == "AUTORIZADO"
        assert "backlog" in depois["operations"]

        # E revogar corta na leitura seguinte.
        revogado = await client.post(
            f"/api/v1/diagnostics/acesso-assistido/{concessao['id']}/revogacao",
            headers=h, json={"motivo": "O atendimento terminou"})
        assert revogado.status_code == 200, revogado.text
        assert revogado.json()["situacao"] == "REVOKED"
        assert revogado.json()["vale_agora"] is False

        cortado = _workspace(tenant_id, concessao["principal"])
        assert cortado["operations"]["acesso"] == "SEM_AUTORIZACAO"
        assert "backlog" not in cortado["operations"]


@pytest.mark.asyncio
async def test_o_escopo_e_conferido_e_nao_e_decorativo():
    """Autorizar o suporte a ver uma coisa não é autorizá-lo a ver outra."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h, tenant_id = ctx["headers"], ctx["tenant"]["id"]
        concessao = _pedir_acesso(tenant_id, escopo=("billing",))
        await client.post(f"/api/v1/diagnostics/acesso-assistido/{concessao['id']}/aprovacao",
                          headers=h, json={"motivo": "Só para a cobrança"})

        workspace = _workspace(tenant_id, concessao["principal"])
        assert workspace["operations"]["acesso"] == "SEM_AUTORIZACAO", (
            "uma autorização de 'billing' abriu o estado operacional"
        )


@pytest.mark.asyncio
async def test_o_prazo_vencido_deixa_de_valer_sem_ninguem_virar_linha():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h, tenant_id = ctx["headers"], ctx["tenant"]["id"]

        # Um pedido cujo prazo passa antes de ser decidido não é aprovável.
        vencido = _pedir_acesso(tenant_id, segundos=2)
        await asyncio.sleep(3)

        recusa = await client.post(
            f"/api/v1/diagnostics/acesso-assistido/{vencido['id']}/aprovacao",
            headers=h, json={"motivo": "Tentando aprovar fora do prazo"})
        assert recusa.status_code == 409, recusa.text
        assert "prazo" in recusa.json()["detail"]

        na_loja = (await client.get("/api/v1/diagnostics/acesso-assistido", headers=h)).json()
        assert na_loja[0]["expirado"] is True
        assert na_loja[0]["vale_agora"] is False


@pytest.mark.asyncio
async def test_recusar_um_pedido_pendente_nao_exige_aprova_lo_antes():
    """Obrigar a aprovar para depois cortar seria pedir que a pessoa abrisse a
    porta para poder fechá-la."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        concessao = _pedir_acesso(ctx["tenant"]["id"])

        recusado = await client.post(
            f"/api/v1/diagnostics/acesso-assistido/{concessao['id']}/revogacao",
            headers=h, json={"motivo": "Não reconheço este pedido"})
        assert recusado.status_code == 200, recusado.text
        assert recusado.json()["situacao"] == "REVOKED"
        assert recusado.json()["vale_agora"] is False


@pytest.mark.asyncio
async def test_a_autorizacao_de_um_tenant_nao_aparece_nem_vale_no_outro():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        a = await _tenant(client)
        b = await _tenant(client)
        concessao = _pedir_acesso(a["tenant"]["id"])

        assert (await client.get("/api/v1/diagnostics/acesso-assistido",
                                 headers=b["headers"])).json() == []

        # E o vizinho não aprova o que não é dele.
        atravessando = await client.post(
            f"/api/v1/diagnostics/acesso-assistido/{concessao['id']}/aprovacao",
            headers=b["headers"], json={"motivo": "Aprovando o do vizinho"})
        assert atravessando.status_code == 404, atravessando.text


@pytest.mark.asyncio
async def test_a_autorizacao_aprovada_para_de_valer_quando_o_prazo_vence():
    """O prazo é o que limita o acesso — e limitar tem de acontecer sozinho.

    Este é o caso que o teste de "não dá para aprovar fora do prazo" **não**
    cobria: uma autorização aprovada dentro do prazo, que vence enquanto está
    valendo. Sem conferir a expiração na porta, ela continuaria abrindo o
    estado operacional para sempre, e "expira em 4 horas" seria só um texto na
    tela.

    Nada vira a linha quando o prazo passa: ela continua `APPROVED` no banco e
    simplesmente deixa de valer. É a mesma disciplina de "vencida" na UX-10.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h, tenant_id = ctx["headers"], ctx["tenant"]["id"]

        concessao = _pedir_acesso(tenant_id, segundos=4)
        aprovado = await client.post(
            f"/api/v1/diagnostics/acesso-assistido/{concessao['id']}/aprovacao",
            headers=h, json={"motivo": "Autorizei uma janela curta"})
        assert aprovado.status_code == 200, aprovado.text
        assert aprovado.json()["vale_agora"] is True

        # Dentro do prazo, a porta abre.
        assert _workspace(tenant_id, concessao["principal"])["operations"]["acesso"] == "AUTORIZADO"

        await asyncio.sleep(5)

        # Passado o prazo, ela fecha — sem ninguém ter tocado em nada.
        assert _workspace(tenant_id, concessao["principal"])["operations"]["acesso"] == "SEM_AUTORIZACAO"

        na_loja = (await client.get("/api/v1/diagnostics/acesso-assistido", headers=h)).json()
        atual = next(a for a in na_loja if a["id"] == concessao["id"])
        # A situação gravada não mudou; o que mudou foi a hora.
        assert atual["situacao"] == "APPROVED"
        assert atual["expirado"] is True
        assert atual["vale_agora"] is False


# ---------------------------------------------------------------------------
# A revisão de 09/09/2026. A autorização é nominal, a migração preserva o
# histórico, e o diagnóstico só afirma o que mediu.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_autorizacao_vale_para_quem_pediu_e_nao_para_a_plataforma_inteira():
    """O defeito central da primeira versão.

    A porta conferia tenant, situação, prazo e escopo — e **não conferia quem
    estava lendo**. Uma autorização dada a uma pessoa abria o estado
    operacional para qualquer outra que alcançasse o console, enquanto a tela
    do lojista prometia dizer "quem tem acesso aos seus dados".

    Autorizar é nominal: quem pediu é quem entra. Autorizar uma equipe seria
    outra coisa, teria de estar escrita no pedido, e é decisão do dono.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h, tenant_id = ctx["headers"], ctx["tenant"]["id"]

        # Duas pessoas de suporte, ambas com o mesmo papel de plataforma.
        with Session(engine) as session:
            quem_pediu, _ = _plataforma(session)
            outra_pessoa, _ = _plataforma(session)
            concessao = request_support(
                uuid.UUID(tenant_id),
                SupportGrantCreate(
                    scope=["operations"], reason="Investigar lentidão relatada",
                    expires_at=datetime.utcnow() + timedelta(hours=4),
                ),
                quem_pediu, session,
            )
            grant_id = str(concessao.id)

        aprovado = await client.post(
            f"/api/v1/diagnostics/acesso-assistido/{grant_id}/aprovacao",
            headers=h, json={"motivo": "Autorizei esta pessoa"})
        assert aprovado.status_code == 200, aprovado.text

        # Para quem pediu, a porta abre.
        with Session(engine) as session:
            dela = control_workspace(uuid.UUID(tenant_id), quem_pediu, session)
        assert dela["operations"]["acesso"] == "AUTORIZADO"

        # Para a colega — mesmo papel, mesmo console — não abre.
        with Session(engine) as session:
            da_colega = control_workspace(uuid.UUID(tenant_id), outra_pessoa, session)
        assert da_colega["operations"]["acesso"] == "SEM_AUTORIZACAO", (
            "a autorização de uma pessoa abriu o acesso para outra"
        )
        assert "backlog" not in da_colega["operations"]


@pytest.mark.asyncio
async def test_a_tela_do_lojista_diz_quem_esta_pedindo():
    """"Quem tem acesso aos seus dados" tem de nomear alguém.

    Antes, a resposta trazia motivo, escopo e prazo — e nenhuma identificação.
    O lojista autorizava um pedido anônimo.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h, tenant_id = ctx["headers"], ctx["tenant"]["id"]

        with Session(engine) as session:
            principal, pessoa = _plataforma(session)
            request_support(
                uuid.UUID(tenant_id),
                SupportGrantCreate(
                    scope=["operations"], reason="Investigar lentidão relatada",
                    expires_at=datetime.utcnow() + timedelta(hours=4),
                ),
                principal, session,
            )
            nome_esperado = pessoa.full_name
            email_esperado = pessoa.email

        na_loja = (await client.get("/api/v1/diagnostics/acesso-assistido", headers=h)).json()
        assert len(na_loja) == 1
        assert na_loja[0]["solicitante"] == nome_esperado
        assert na_loja[0]["solicitante_email"] == email_esperado


@pytest.mark.asyncio
async def test_revogar_e_expirar_fecham_a_porta_para_quem_pediu():
    """As duas formas de a autorização deixar de valer, medidas na porta."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h, tenant_id = ctx["headers"], ctx["tenant"]["id"]

        # --- revogar
        with Session(engine) as session:
            profissional, _ = _plataforma(session)
            concessao = request_support(
                uuid.UUID(tenant_id),
                SupportGrantCreate(
                    scope=["operations"], reason="Atendimento em andamento",
                    expires_at=datetime.utcnow() + timedelta(hours=4),
                ),
                profissional, session,
            )
            grant_id = str(concessao.id)
        await client.post(f"/api/v1/diagnostics/acesso-assistido/{grant_id}/aprovacao",
                          headers=h, json={"motivo": "Autorizei"})
        with Session(engine) as session:
            assert control_workspace(
                uuid.UUID(tenant_id), profissional, session)["operations"]["acesso"] == "AUTORIZADO"

        await client.post(f"/api/v1/diagnostics/acesso-assistido/{grant_id}/revogacao",
                          headers=h, json={"motivo": "O atendimento terminou"})
        with Session(engine) as session:
            assert control_workspace(
                uuid.UUID(tenant_id), profissional, session)["operations"]["acesso"] == "SEM_AUTORIZACAO"

        # --- expirar
        with Session(engine) as session:
            outro, _ = _plataforma(session)
            curta = request_support(
                uuid.UUID(tenant_id),
                SupportGrantCreate(
                    scope=["operations"], reason="Janela curta",
                    expires_at=datetime.utcnow() + timedelta(seconds=4),
                ),
                outro, session,
            )
            curta_id = str(curta.id)
        await client.post(f"/api/v1/diagnostics/acesso-assistido/{curta_id}/aprovacao",
                          headers=h, json={"motivo": "Autorizei uma janela curta"})
        with Session(engine) as session:
            assert control_workspace(
                uuid.UUID(tenant_id), outro, session)["operations"]["acesso"] == "AUTORIZADO"

        await asyncio.sleep(5)
        with Session(engine) as session:
            assert control_workspace(
                uuid.UUID(tenant_id), outro, session)["operations"]["acesso"] == "SEM_AUTORIZACAO"


@pytest.mark.asyncio
async def test_o_diagnostico_afirma_so_o_que_mediu():
    """Frase que promete mais do que a medida entrega é pior do que frase
    nenhuma: o lojista para de procurar.

    Um `SELECT 1` prova que o banco respondeu, não que gravação funciona. A
    fila do servidor prova o que está nela, não o que ainda está num aparelho
    desconectado.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        corpo = (await client.get("/api/v1/diagnostics", headers=ctx["headers"])).json()
        por_chave = {v["chave"]: v for v in corpo["verificacoes"]}

        banco = por_chave["dados"]
        assert banco["titulo"] == "Conexão com o banco"
        assert banco["resumo"] == "Conexão com o banco respondendo."
        assert "gravação" not in banco["resumo"], (
            "um SELECT 1 não comprova gravação"
        )

        fila = por_chave["sincronizacao"]
        assert fila["titulo"] == "Fila de envios do servidor"
        assert "fila do servidor" in fila["resumo"]
        # A abrangência vai no dado, para nenhuma tela concluir mais que a medida.
        assert "aparelho desconectado" in fila["detalhes"]["abrange"]
        assert "Tudo o que você registrou" not in fila["resumo"]


@pytest.mark.asyncio
async def test_o_historico_sobrevive_a_reaprovacao():
    """A sequência inteira: pedido → aprovação → invalidação → nova aprovação.

    A 095 preservava a aprovação anterior nas colunas da concessão, e isso
    resolvia **um** momento. Não resolvia o seguinte: aprovar de novo
    sobrescreve `approved_by` e `approved_at` e limpa a marca da invalidação,
    porque estado atual é sempre uma coisa só. A transição sumia.

    Agora cada decisão é um lançamento, nada é sobrescrito, e o histórico se lê
    de ponta a ponta — inclusive a invalidação que a nova aprovação apagou da
    linha.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h, tenant_id = ctx["headers"], ctx["tenant"]["id"]

        # --- 1. o suporte pede
        with Session(engine) as session:
            profissional, pessoa = _plataforma(session)
            # O nome sai da sessão agora: depois de fechá-la, o objeto está
            # solto e ler um atributo tenta recarregar do banco.
            nome_de_quem_pediu = pessoa.full_name
            concessao = request_support(
                uuid.UUID(tenant_id),
                SupportGrantCreate(
                    scope=["operations"], reason="Investigar fila travada",
                    expires_at=datetime.utcnow() + timedelta(hours=6),
                ),
                profissional, session,
            )
            grant_id = str(concessao.id)

        # --- 2. o responsável aprova
        primeira = await client.post(
            f"/api/v1/diagnostics/acesso-assistido/{grant_id}/aprovacao",
            headers=h, json={"motivo": "Primeira autorização, combinada por telefone"})
        assert primeira.status_code == 200, primeira.text

        # --- 3. a aprovação perde validade, como a 095 fez em massa
        with Session(engine) as session:
            _janela_da_plataforma(session)
            linha = session.get(AssistedSupportGrant, uuid.UUID(grant_id))
            linha.status = SupportGrantStatusEnum.PENDING
            linha.invalidated_at = datetime.utcnow()
            linha.invalidated_reason = "Regra nova exige aprovação do responsável"
            session.add(linha)
            registrar_no_historico(
                session, linha, SupportGrantEventTypeEnum.INVALIDATED,
                motivo=linha.invalidated_reason,
            )
            session.commit()

        # O lojista vê o motivo da queda enquanto ela está em vigor.
        antes = (await client.get("/api/v1/diagnostics/acesso-assistido", headers=h)).json()[0]
        assert antes["invalidada_porque"] == "Regra nova exige aprovação do responsável"
        assert antes["vale_agora"] is False

        # --- 4. o responsável aprova de novo
        segunda = await client.post(
            f"/api/v1/diagnostics/acesso-assistido/{grant_id}/aprovacao",
            headers=h, json={"motivo": "Reautorizei sob a regra nova"})
        assert segunda.status_code == 200, segunda.text
        depois = segunda.json()

        # A linha esqueceu — é o trabalho dela guardar só o estado atual.
        assert depois["invalidada_em"] is None
        assert depois["invalidada_porque"] is None
        assert depois["vale_agora"] is True

        # --- 5. o histórico não esqueceu
        tipos = [lancamento["tipo"] for lancamento in depois["historico"]]
        assert tipos == ["REQUESTED", "APPROVED", "INVALIDATED", "APPROVED"], tipos

        pedido, aprovacao_antiga, queda, aprovacao_nova = depois["historico"]
        assert pedido["quem"] == nome_de_quem_pediu
        assert "Investigar fila travada" in pedido["motivo"]
        assert aprovacao_antiga["motivo"] == "Primeira autorização, combinada por telefone"
        assert queda["motivo"] == "Regra nova exige aprovação do responsável"
        # A invalidação não tem autor: ela veio de uma regra, não de alguém.
        assert queda["quem"] is None
        assert aprovacao_nova["motivo"] == "Reautorizei sob a regra nova"

        # E a ordem é cronológica, para o histórico se ler de cima para baixo.
        marcas = [lancamento["ocorreu_em"] for lancamento in depois["historico"]]
        assert marcas == sorted(marcas)

        # --- 6. revogar também entra, e não apaga o que veio antes
        cortado = (await client.post(
            f"/api/v1/diagnostics/acesso-assistido/{grant_id}/revogacao",
            headers=h, json={"motivo": "O atendimento terminou"})).json()
        assert [l["tipo"] for l in cortado["historico"]] == [
            "REQUESTED", "APPROVED", "INVALIDATED", "APPROVED", "REVOKED",
        ]


@pytest.mark.asyncio
async def test_a_auditoria_da_reaprovacao_diz_o_que_ela_substituiu():
    """O evento tem de carregar os valores que a gravação apagou.

    Sem isso, quem lê a auditoria vê "aprovado" e não sabe que havia uma
    aprovação anterior, nem que ela tinha caído.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h, tenant_id = ctx["headers"], ctx["tenant"]["id"]
        concessao = _pedir_acesso(tenant_id)
        grant_id = concessao["id"]

        await client.post(f"/api/v1/diagnostics/acesso-assistido/{grant_id}/aprovacao",
                          headers=h, json={"motivo": "Primeira"})
        with Session(engine) as session:
            _janela_da_plataforma(session)
            linha = session.get(AssistedSupportGrant, uuid.UUID(grant_id))
            linha.status = SupportGrantStatusEnum.PENDING
            linha.invalidated_at = datetime.utcnow()
            linha.invalidated_reason = "Caiu pela regra nova"
            session.add(linha)
            session.commit()
        await client.post(f"/api/v1/diagnostics/acesso-assistido/{grant_id}/aprovacao",
                          headers=h, json={"motivo": "Segunda"})

        with Session(engine) as session:
            _janela_da_plataforma(session)
            eventos = session.exec(
                select(AuditEvent)
                .where(AuditEvent.target == f"support:{grant_id}",
                       AuditEvent.action == "tenant.support_access.approved")
                .order_by(AuditEvent.created_at)
            ).all()
            assert len(eventos) == 2
            substituido = json.loads(eventos[-1].payload)["substituiu"]

        assert substituido["invalidada_porque"] == "Caiu pela regra nova"
        assert substituido["aprovada_em"] is not None, (
            "o evento não disse que já havia uma aprovação anterior"
        )
