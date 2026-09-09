"""Cancelar e descontar passam a ter duas pessoas, e nenhuma delas some.

Até 07/09/2026 havia dois estados e nenhum era a loja: ou o operador tinha a
permissão e desfazia a venda sozinho, sem testemunha, ou não tinha e o botão
ficava apagado — e a saída prática era o supervisor operar no caixa alheio, o
que grava a venda no nome errado.

Estes testes fixam o contrato da autorização presencial: quem tem autoridade
digita o próprio código no terminal do operador, a permissão vale para aquela
requisição, as duas pessoas ficam registradas, e nada disso é gravado no
cadastro de quem pediu.
"""

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.context import SupervisorElevation, authorization_trail, authorize_tenant_context
from app.core.database import engine
from app.core.security import AuthPrincipal
from app.core.tenancy import set_platform_db_context
from app.models.identity import (
    AuthIdentity, Employee, EmployeeStatusEnum, Membership, MembershipStatusEnum,
    OperationalCredential, RoleEnum, Store, Tenant, TenantStatusEnum, User,
)
from app.models.platform import TenantCapability
from app.services import operational_access_service


def _principal(subject: str) -> AuthPrincipal:
    return AuthPrincipal(
        subject=subject, email=f"{subject}@example.test", session_id=str(uuid.uuid4()),
        assurance_level="aal1", claims={"sub": subject},
    )


def _cenario(supervisor_role: RoleEnum = RoleEnum.SUPERVISOR):
    """Um caixa que não pode cancelar e uma supervisora que pode."""
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"Balcao {suffix}", slug=f"balcao-{suffix}", status=TenantStatusEnum.ACTIVE)
        session.add(tenant)
        session.flush()
        store = Store(tenant_id=tenant.id, name="Matriz", code=f"BLC-{suffix}")
        session.add(store)
        session.flush()
        session.add(TenantCapability(tenant_id=tenant.id, key="supervisor_override", enabled=True))
        session.add(TenantCapability(tenant_id=tenant.id, key="counter_order", enabled=True))

        caixa_subject = str(uuid.uuid4())
        caixa = User(email=f"caixa-{suffix}@example.test", full_name="Operadora")
        supervisora = User(email=f"sup-{suffix}@example.test", full_name="Supervisora Marta")
        session.add(caixa)
        session.add(supervisora)
        session.flush()
        session.add(AuthIdentity(user_id=caixa.id, provider="supabase", provider_subject=caixa_subject))
        vinculo_caixa = Membership(
            user_id=caixa.id, tenant_id=tenant.id, store_id=store.id,
            role=RoleEnum.CASHIER, status=MembershipStatusEnum.ACTIVE,
        )
        vinculo_sup = Membership(
            user_id=supervisora.id, tenant_id=tenant.id, store_id=store.id,
            role=supervisor_role, status=MembershipStatusEnum.ACTIVE,
        )
        session.add(vinculo_caixa)
        session.add(vinculo_sup)
        session.flush()
        empregada = Employee(
            tenant_id=tenant.id, user_id=supervisora.id, home_store_id=store.id,
            employee_number="SUP-01", full_name="Supervisora Marta",
            status=EmployeeStatusEnum.ACTIVE,
        )
        session.add(empregada)
        session.flush()
        salt, pin_hash, iterations = operational_access_service.new_pin_secret("4826")
        session.add(OperationalCredential(
            tenant_id=tenant.id, store_id=store.id, user_id=supervisora.id,
            membership_id=vinculo_sup.id, employee_id=empregada.id,
            employee_code="SUP-01", pin_salt=salt, pin_hash=pin_hash,
            pin_iterations=iterations, pin_activated_at=datetime.utcnow(),
        ))
        session.commit()
        return tenant.id, store.id, caixa_subject


CANCELAR = ("POST", f"/api/v1/sales/{uuid.uuid4()}/cancel")


def test_the_till_alone_cannot_cancel():
    tenant_id, store_id, caixa = _cenario()
    with Session(engine) as session:
        with pytest.raises(HTTPException) as recusa:
            authorize_tenant_context(session, _principal(caixa), tenant_id, store_id, *CANCELAR)
    assert recusa.value.status_code == 403
    # Esta é a recusa que a operadora lê no balcão. Ela nomeia a operação em
    # português e não vaza a chave da permissão — foi assim que "Missing
    # permission: sale.cancel" apareceu na tela, na travessia hom04.
    assert recusa.value.detail == "Você não tem autorização para cancelar venda. Peça a quem tem."
    assert "sale.cancel" not in recusa.value.detail


def test_the_supervisor_at_the_counter_authorizes_this_one_operation():
    tenant_id, store_id, caixa = _cenario()
    with Session(engine) as session:
        context = authorize_tenant_context(
            session, _principal(caixa), tenant_id, store_id, *CANCELAR,
            elevation=SupervisorElevation(employee_code="SUP-01", pin="4826"),
        )
    assert "sale.cancel" in context.permissions
    assert context.authorized_by_name == "Supervisora Marta"
    assert context.authorized_by_code == "SUP-01"
    assert context.authorized_permission == "sale.cancel"
    # A auditoria guarda quem permitiu; quem pediu já está no actor do registro.
    trilha = authorization_trail(context)
    assert trilha["authorized_by_name"] == "Supervisora Marta"
    assert trilha["authorized_permission"] == "sale.cancel"

    # E não sobrou poder nenhum no cadastro do operador.
    with Session(engine) as session:
        with pytest.raises(HTTPException) as depois:
            authorize_tenant_context(session, _principal(caixa), tenant_id, store_id, *CANCELAR)
    assert depois.value.status_code == 403


def test_a_wrong_pin_does_not_authorize_and_does_not_say_who_exists():
    tenant_id, store_id, caixa = _cenario()
    with Session(engine) as session:
        with pytest.raises(HTTPException) as errado:
            authorize_tenant_context(
                session, _principal(caixa), tenant_id, store_id, *CANCELAR,
                elevation=SupervisorElevation(employee_code="SUP-01", pin="7351"),
            )
    assert errado.value.status_code == 401
    assert errado.value.detail == "Código ou PIN inválidos."

    with Session(engine) as session:
        with pytest.raises(HTTPException) as inexistente:
            authorize_tenant_context(
                session, _principal(caixa), tenant_id, store_id, *CANCELAR,
                elevation=SupervisorElevation(employee_code="NAO-EXISTE", pin="4826"),
            )
    # A recusa é a mesma dos dois lados: não enumera quem trabalha na loja.
    assert inexistente.value.detail == errado.value.detail


def test_authorizing_requires_authority_and_says_so_by_name():
    """Identidade provada e autoridade ausente: a pessoa precisa saber disso."""
    tenant_id, store_id, caixa = _cenario(supervisor_role=RoleEnum.OPERATOR)
    with Session(engine) as session:
        with pytest.raises(HTTPException) as sem_autoridade:
            authorize_tenant_context(
                session, _principal(caixa), tenant_id, store_id, *CANCELAR,
                elevation=SupervisorElevation(employee_code="SUP-01", pin="4826"),
            )
    assert sem_autoridade.value.status_code == 403
    assert "Supervisora Marta" in sem_autoridade.value.detail


def test_no_one_can_authorize_what_the_shop_did_not_contract():
    """Autorizar é emprestar autoridade, não contratar módulo."""
    tenant_id, store_id, caixa = _cenario()
    with Session(engine) as session:
        set_platform_db_context(session)
        contratada = session.exec(select(TenantCapability).where(
            TenantCapability.tenant_id == tenant_id,
            TenantCapability.key == "supervisor_override",
        )).first()
        contratada.enabled = False
        session.add(contratada)
        session.commit()

    with Session(engine) as session:
        with pytest.raises(HTTPException) as sem_contrato:
            authorize_tenant_context(
                session, _principal(caixa), tenant_id, store_id, *CANCELAR,
                elevation=SupervisorElevation(employee_code="SUP-01", pin="4826"),
            )
    assert sem_contrato.value.status_code == 403
    assert "supervisor_override" in sem_contrato.value.detail
