"""Um tenant de food service, para percorrer os dois destinos que faltavam.

A UX-05 deixou dois cards sem auditoria — **Ambientes e Mesas** e **Provedores
de pagamento** — e a razão registrada na época era "o acervo de homologação não
contrata FOOD_SERVICE nem tef". Verificando agora, a razão é mais precisa que
isso, e vale escrever:

* `table_service` **estava** semeado como entitlement e mesmo assim não chegava
  ao acesso efetivo. `capability_allowed_by_activity` recusa atender mesa a quem
  não declarou food service, e o acervo não declarava atividade nenhuma. Não era
  falta de capability: era falta de **atividade**;
* `tef` não é vendável. Ele só entra pelo caminho que o ADR-031 abriu para
  homologação: `homologation_override` na configuração do entitlement, com a
  capability fora da lista de implementadas e as dependências dela já valendo.
  Ligar TEF onde pagamentos não vale continua sendo recusado.

Este roteiro monta exatamente isso, pelos mesmos mecanismos do produto: atribui
a revisão de perfil FOOD_SERVICE (é dela que a atividade é lida quando não há
contrato versionado) e concede o override de homologação para o TEF.

Ele também semeia uma gerente com `table.manage` **negado** na concessão do
vínculo: é assim que se prova, na tela, que ver o mapa não é poder mudá-lo.
Perfil de caixa não serve para isso — caixa não entra na Gestão.

**O que ele não faz:** criar ambiente, mesa ou provedor. Isso é jornada, e
jornada se percorre na tela.
"""

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import jwt
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.identity import (
    AuthIdentity, Membership, MembershipStatusEnum, PermissionGrant,
    PermissionGrantEffectEnum, Register, RoleEnum, Store, Tenant, TenantStatusEnum, User,
)
from app.models.device import OperationalDevice, OperationalDeviceTypeEnum
from app.models.platform import (
    CapabilityProfileRevision, TenantCapability, TenantProfileAssignment,
)

#: O que um food service contrata. `table_service` é o que abre Ambientes e
#: Mesas; sem a atividade declarada abaixo, ele não vale nem estando aqui.
CAPABILITIES = (
    "cash_management", "catalog", "combos", "counter_order", "customer",
    "delivery_orders", "inventory", "kitchen_routing", "modifiers", "payments",
    "receivables", "supervisor_override", "table_service",
)

#: TEF não é vendável, e por isso não entra na lista acima. Ele entra pela
#: exceção de homologação do ADR-031, declarada na própria linha.
CAPABILITY_DE_HOMOLOGACAO = "tef"

PERFIL = "FOOD_SERVICE"


def _token(subject: str, email: str) -> str:
    agora = int(datetime.now(timezone.utc).timestamp())
    return jwt.encode(
        {
            "sub": subject, "email": email, "aud": "authenticated", "role": "authenticated",
            "iat": agora, "exp": agora + 28800, "session_id": str(uuid.uuid4()),
            "aal": "aal1", "app_metadata": {"provider": "email"},
        },
        settings.AUTH_TEST_SECRET, algorithm="HS256",
    )


def semear(saida: Path) -> None:
    sufixo = uuid.uuid4().hex[:8]
    subject = str(uuid.uuid4())
    email = f"gestora-food-{sufixo}@dashem.test"

    with Session(engine) as session:
        # A política das tabelas é forçada: sem janela aberta, nem inserir dá.
        set_platform_db_context(session)
        revisao = session.exec(
            select(CapabilityProfileRevision).where(
                CapabilityProfileRevision.profile_key == PERFIL,
                CapabilityProfileRevision.status == "ACTIVE",
            ).order_by(CapabilityProfileRevision.version.desc())
        ).first()
        if revisao is None:
            raise SystemExit(
                f"Nenhuma revisão ACTIVE do perfil {PERFIL}. Sem ela a atividade "
                "não é declarada e Ambientes e Mesas continua invisível."
            )

        # PROVISIONING é recusado na borda com "Tenant is unavailable": um
        # tenant que não terminou de nascer não atende.
        tenant = Tenant(name=f"Cozinha de Homologação {sufixo}", slug=f"cozinha-{sufixo}",
                        status=TenantStatusEnum.TRIAL)
        gestora = User(email=email, full_name="Renata Nogueira",
                       password_setup_completed_at=datetime.now(timezone.utc))
        session.add_all([tenant, gestora])
        session.flush()
        session.add(AuthIdentity(
            user_id=gestora.id, provider="supabase", provider_subject=subject,
            provider_email=email, email_verified=True,
        ))
        session.add(Membership(
            user_id=gestora.id, tenant_id=tenant.id,
            role=RoleEnum.TENANT_OWNER, status=MembershipStatusEnum.ACTIVE,
        ))

        # A atividade vem daqui quando não há contrato versionado — é a mesma
        # leitura que o console do Owner faz.
        session.add(TenantProfileAssignment(
            tenant_id=tenant.id, revision_id=revisao.id, status="ACTIVE",
            reason="Homologação das jornadas de mesa e de provedor de pagamento",
            assigned_by=gestora.id,
        ))

        session.add_all([
            TenantCapability(tenant_id=tenant.id, key=chave, enabled=True)
            for chave in CAPABILITIES
        ])
        session.add(TenantCapability(
            tenant_id=tenant.id, key=CAPABILITY_DE_HOMOLOGACAO, enabled=True,
            configuration={"homologation_override": True},
        ))

        # Uma segunda pessoa que **vê o mapa e não o configura**.
        #
        # A primeira tentativa aqui usou um perfil de caixa, e ela não serve:
        # caixa não entra na Gestão — a tela recusa com "terminal não
        # autorizado", porque a entrada dele é a operação, com terminal
        # autorizado. E dentro da Gestão nenhum perfil de sistema tem
        # `table.read` sem `table.manage`.
        #
        # A distinção existe de verdade por **concessão**: uma gerente com
        # `table.manage` negado na própria linha de vínculo. É o mesmo
        # mecanismo que a UX-13 usa para autoridade presencial, e é assim que
        # um lojista real tira uma permissão de alguém.
        subject_limitada = str(uuid.uuid4())
        email_limitada = f"gerente-limitada-{sufixo}@dashem.test"
        limitada = User(email=email_limitada, full_name="Tiago Prado",
                        password_setup_completed_at=datetime.now(timezone.utc))
        session.add(limitada)
        session.flush()
        session.add(AuthIdentity(
            user_id=limitada.id, provider="supabase", provider_subject=subject_limitada,
            provider_email=email_limitada, email_verified=True,
        ))
        vinculo_limitado = Membership(
            user_id=limitada.id, tenant_id=tenant.id,
            role=RoleEnum.MANAGER, status=MembershipStatusEnum.ACTIVE,
        )
        session.add(vinculo_limitado)
        session.flush()
        session.add(PermissionGrant(
            tenant_id=tenant.id, membership_id=vinculo_limitado.id,
            permission_key="table.manage", effect=PermissionGrantEffectEnum.DENY,
            reason="Homologação: conferir que ver o mapa não é poder mudá-lo",
            granted_by=gestora.id,
        ))

        loja = Store(tenant_id=tenant.id, name="Salão Homologação",
                     code=f"SAL-{sufixo}", is_headquarters=True)
        session.add(loja)
        session.flush()

        caixa = Register(tenant_id=tenant.id, store_id=loja.id,
                         name="Caixa do salão", code=f"CXS-{sufixo}")
        session.add(caixa)
        session.flush()
        session.add(OperationalDevice(
            tenant_id=tenant.id, store_id=loja.id, code=f"POS-{sufixo}",
            name="Terminal do salão", device_type=OperationalDeviceTypeEnum.POS,
            register_id=caixa.id,
        ))
        session.commit()

        fixture = {
            "tenant_id": str(tenant.id), "tenant_name": tenant.name,
            "store_id": str(loja.id), "store_name": loja.name,
            "manager_email": email, "manager_token": _token(subject, email),
            "register_id": str(caixa.id),
            "limited_email": email_limitada,
            "limited_token": _token(subject_limitada, email_limitada),
            "perfil": PERFIL, "revisao": revisao.version,
        }

    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps(fixture, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"food service semeado: {tenant.name} · perfil {PERFIL} {revisao.version}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    semear(parser.parse_args().output)
