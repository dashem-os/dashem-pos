"""Quem pode o quê, dito na tela de acessos — e escrito onde o servidor já lê.

O ADR-028 tornou cancelar e descontar operações de duas pessoas. A regra
funcionava e não era configurável: mudar quem pode cancelar exigia trocar o
perfil da pessoa ou escrever no banco.

Estes testes fixam as três coisas que a UX-13 precisa garantir:

1. a marcação escreve nas **concessões que já existem**, que é a mesma fonte que
   o servidor consulta ao decidir se abre o diálogo de autorização no PDV —
   marcar aqui e o PDV mudar de comportamento não são dois efeitos;
2. **ninguém amplia a própria autoridade**, ou a autorização presencial deixaria
   de ser de duas pessoas para ser de uma;
3. a alteração fica na **auditoria**, com autor e horário, como qualquer outra.
"""

import uuid

from sqlmodel import Session, select

from app.core.context import TenantContext
from app.core.database import engine
from app.core.permissions import effective_access, profile_permissions
from app.core.tenancy import set_platform_db_context
from app.models.identity import (
    Membership, MembershipStatusEnum, Permission, PermissionGrant,
    PermissionGrantEffectEnum, RoleEnum, Store, Tenant, User,
)
from app.models.reliability import AuditEvent


def _equipe(session: Session, papel: RoleEnum = RoleEnum.CASHIER):
    sufixo = uuid.uuid4().hex[:8]
    tenant = Tenant(name=f"Autoridade {sufixo}", slug=f"autoridade-{sufixo}")
    session.add(tenant)
    session.flush()
    loja = Store(tenant_id=tenant.id, name="Matriz", code=f"M-{sufixo}")
    session.add(loja)
    session.flush()
    usuario = User(email=f"pessoa-{sufixo}@dashem.test", full_name="Pessoa da Equipe")
    session.add(usuario)
    session.flush()
    vinculo = Membership(
        tenant_id=tenant.id, user_id=usuario.id, store_id=loja.id,
        role=papel, status=MembershipStatusEnum.ACTIVE,
    )
    session.add(vinculo)
    session.flush()
    return tenant, loja, vinculo


def test_as_operacoes_presenciais_vem_marcadas_no_dado():
    """A lista não é constante do código: é a coluna da própria permissão."""
    with Session(engine) as session:
        set_platform_db_context(session)
        presenciais = {
            p.key for p in session.exec(
                select(Permission).where(Permission.requires_presence.is_(True))
            ).all()
        }
        assert "sale.cancel" in presenciais
        assert "sale.discount" in presenciais
        # E o que não é presencial não entra por engano.
        assert "catalog.read" not in presenciais


def test_conceder_faz_a_pessoa_agir_sozinha_no_mesmo_calculo_do_servidor():
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant, loja, vinculo = _equipe(session)

        do_perfil = profile_permissions(session, vinculo)
        assert "sale.cancel" not in do_perfil, "o caixa não deveria cancelar sozinho pelo perfil"

        session.add(PermissionGrant(
            tenant_id=tenant.id, store_id=None, membership_id=vinculo.id,
            permission_key="sale.cancel", effect=PermissionGrantEffectEnum.ALLOW,
            reason="Assume o turno da noite sozinha.",
        ))
        session.flush()

        # O mesmo cálculo que o PDV consulta: não há uma segunda fonte.
        acesso = effective_access(session, vinculo, loja.id)
        assert "sale.cancel" in acesso.permissions
        session.rollback()


def test_recusar_tira_a_autoridade_que_vinha_do_perfil():
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant, loja, vinculo = _equipe(session, papel=RoleEnum.MANAGER)

        do_perfil = profile_permissions(session, vinculo)
        assert "sale.cancel" in do_perfil, "o gerente deveria cancelar sozinho pelo perfil"

        session.add(PermissionGrant(
            tenant_id=tenant.id, store_id=None, membership_id=vinculo.id,
            permission_key="sale.cancel", effect=PermissionGrantEffectEnum.DENY,
            reason="Em treinamento; cancela com acompanhamento.",
        ))
        session.flush()

        acesso = effective_access(session, vinculo, loja.id)
        assert "sale.cancel" not in acesso.permissions
        session.rollback()


def test_a_alteracao_de_autoridade_fica_na_auditoria():
    """Auditoria com autor e horário, como qualquer outra alteração."""
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant, loja, vinculo = _equipe(session)
        autor = uuid.uuid4()

        from app.services import reliability_service
        reliability_service.write_audit_and_outbox(
            session, tenant_id=tenant.id, store_id=loja.id, actor_id=autor,
            action="tenant.team.authority_changed", target=f"membership:{vinculo.id}",
            audit_payload={"operacao": "sale.cancel", "sozinho": True},
            aggregate_type="membership", aggregate_id=str(vinculo.id),
            event_type="tenant.team.authority_changed",
            outbox_payload={"operacao": "sale.cancel", "sozinho": True},
        )
        session.flush()

        registro = session.exec(select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.action == "tenant.team.authority_changed",
        )).first()
        assert registro is not None
        assert registro.actor_id == autor
        assert registro.created_at is not None
        assert "sale.cancel" in registro.payload
        session.rollback()


def test_concessao_e_por_pessoa_e_nao_vaza_para_a_equipe():
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant, loja, vinculo = _equipe(session)
        outro_usuario = User(email=f"outro-{uuid.uuid4().hex[:8]}@dashem.test", full_name="Outra Pessoa")
        session.add(outro_usuario)
        session.flush()
        outro = Membership(
            tenant_id=tenant.id, user_id=outro_usuario.id, store_id=loja.id,
            role=RoleEnum.CASHIER, status=MembershipStatusEnum.ACTIVE,
        )
        session.add(outro)
        session.flush()

        session.add(PermissionGrant(
            tenant_id=tenant.id, store_id=None, membership_id=vinculo.id,
            permission_key="sale.discount", effect=PermissionGrantEffectEnum.ALLOW,
            reason="Negocia com o cliente do balcão.",
        ))
        session.flush()

        assert "sale.discount" in effective_access(session, vinculo, loja.id).permissions
        assert "sale.discount" not in effective_access(session, outro, loja.id).permissions
        session.rollback()


def test_ninguem_amplia_a_propria_autoridade():
    """A guarda que sustenta a regra inteira.

    Quem tem a tela de acessos poderia se conceder o cancelamento e passar a
    cancelar sozinho — e a autorização presencial deixaria de ser de duas
    pessoas para ser de uma. O pedido é recusado quando o alvo é o próprio
    vínculo de quem pede.
    """
    from fastapi import HTTPException
    from app.api.v1.endpoints.team import MarcacaoDeAutoridade, marcar_autoridade

    with Session(engine) as session:
        set_platform_db_context(session)
        tenant, loja, vinculo = _equipe(session, papel=RoleEnum.MANAGER)
        contexto = TenantContext(
            tenant_id=tenant.id, store_id=loja.id, user_id=vinculo.user_id,
            membership_id=vinculo.id, role=RoleEnum.MANAGER,
        )
        pedido = MarcacaoDeAutoridade(
            chave="sale.cancel", sozinho=True, motivo="Preciso cancelar no meu turno.",
        )
        try:
            marcar_autoridade(vinculo.id, pedido, context=contexto, session=session)
            raise AssertionError("ampliar a própria autoridade deveria ser recusado")
        except HTTPException as recusa:
            assert recusa.status_code == 403
            assert "própria autoridade" in recusa.detail
        session.rollback()


def test_reduzir_a_propria_autoridade_continua_permitido():
    """Tirar de si mesmo não é o risco: quem abre mão pode abrir mão."""
    from app.api.v1.endpoints.team import MarcacaoDeAutoridade, marcar_autoridade

    with Session(engine) as session:
        set_platform_db_context(session)
        tenant, loja, vinculo = _equipe(session, papel=RoleEnum.MANAGER)
        contexto = TenantContext(
            tenant_id=tenant.id, store_id=loja.id, user_id=vinculo.user_id,
            membership_id=vinculo.id, role=RoleEnum.MANAGER,
        )
        marcar_autoridade(
            vinculo.id,
            MarcacaoDeAutoridade(chave="sale.cancel", sozinho=False, motivo="Passo a pedir a outra pessoa."),
            context=contexto, session=session,
        )
        assert "sale.cancel" not in effective_access(session, vinculo, loja.id).permissions
        session.rollback()


def test_so_operacao_presencial_entra_por_aqui():
    """A tela fala em operações, não em chaves: isto não é editor de permissão."""
    from fastapi import HTTPException
    from app.api.v1.endpoints.team import MarcacaoDeAutoridade, marcar_autoridade

    with Session(engine) as session:
        set_platform_db_context(session)
        tenant, loja, vinculo = _equipe(session)
        contexto = TenantContext(tenant_id=tenant.id, store_id=loja.id, user_id=uuid.uuid4())
        try:
            marcar_autoridade(
                vinculo.id,
                MarcacaoDeAutoridade(chave="catalog.read", sozinho=True, motivo="Quero dar acesso ao catálogo."),
                context=contexto, session=session,
            )
            raise AssertionError("permissão não presencial não deveria ser marcável aqui")
        except HTTPException as recusa:
            assert recusa.status_code == 422
        session.rollback()


def test_marcar_igual_ao_perfil_apaga_a_excecao_em_vez_de_guardar_uma_falsa():
    from app.api.v1.endpoints.team import MarcacaoDeAutoridade, marcar_autoridade

    with Session(engine) as session:
        set_platform_db_context(session)
        tenant, loja, vinculo = _equipe(session)
        contexto = TenantContext(tenant_id=tenant.id, store_id=loja.id, user_id=uuid.uuid4())

        # Concede, depois devolve ao que o perfil já dizia.
        marcar_autoridade(vinculo.id, MarcacaoDeAutoridade(
            chave="sale.cancel", sozinho=True, motivo="Turno da noite sozinha."), context=contexto, session=session)
        assert session.exec(select(PermissionGrant).where(
            PermissionGrant.membership_id == vinculo.id)).first() is not None

        marcar_autoridade(vinculo.id, MarcacaoDeAutoridade(
            chave="sale.cancel", sozinho=False, motivo="Voltou a pedir autorização."), context=contexto, session=session)
        # O caixa já não cancelava pelo perfil: guardar uma recusa aqui seria
        # registrar uma exceção que não é exceção.
        assert session.exec(select(PermissionGrant).where(
            PermissionGrant.membership_id == vinculo.id)).first() is None
        session.rollback()
