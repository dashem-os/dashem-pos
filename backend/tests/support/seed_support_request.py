"""Semeia um pedido de acesso assistido, como o suporte faria.

A travessia da UX-12 percorre o lado do **lojista**: ver o pedido, autorizar,
cortar. O pedido em si nasce do outro lado do produto, e ele não passa pelo
bypass de autenticação do servidor de teste — exige vínculo de plataforma e
segundo fator. Então este roteiro faz o que o suporte faria, direto no banco,
com um usuário de plataforma de verdade.

Sem isto, a travessia teria de inventar a linha na mão, e provaria a tela contra
um dado que nenhum caminho do produto produz.
"""

import argparse
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session

from app.api.v1.endpoints.control import SupportGrantCreate, request_support
from app.core.database import engine
from app.core.security import AuthPrincipal
from app.models.identity import AuthIdentity, User
from app.models.platform import PlatformMembership, PlatformRoleEnum

MOTIVO = "Investigar por que os registros não estavam sincronizando"


def semear(tenant_id: uuid.UUID, horas: int, saida: Path) -> None:
    with Session(engine) as session:
        subject = str(uuid.uuid4())
        pessoa = User(email=f"suporte-{subject}@dashem.test", full_name="Suporte Dashem")
        session.add(pessoa)
        session.flush()
        session.add(AuthIdentity(
            user_id=pessoa.id, provider="supabase", provider_subject=subject,
            provider_email=pessoa.email, email_verified=True,
        ))
        session.add(PlatformMembership(user_id=pessoa.id, role=PlatformRoleEnum.PLATFORM_OWNER))
        session.commit()
        session.refresh(pessoa)

        principal = AuthPrincipal(
            subject=subject, email=pessoa.email, session_id=str(uuid.uuid4()),
            assurance_level="aal2", claims={"sub": subject, "aal": "aal2"}, provider="email",
        )
        concessao = request_support(
            tenant_id,
            SupportGrantCreate(
                scope=["operations"], reason=MOTIVO,
                expires_at=datetime.utcnow() + timedelta(hours=horas),
            ),
            principal, session,
        )
        dados = {
            "id": str(concessao.id), "tenant_id": str(tenant_id),
            "motivo": concessao.reason, "escopo": list(concessao.scope),
            "expira_em": concessao.expires_at.isoformat(),
            "situacao": concessao.status.value,
            # A autorização é nominal: a travessia confere que a tela nomeia
            # quem pediu, e para isso precisa saber quem foi.
            "solicitante": pessoa.full_name,
            "solicitante_email": pessoa.email,
        }

    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"pedido de acesso semeado: {dados['id']} · {dados['situacao']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=uuid.UUID)
    parser.add_argument("--horas", default=4, type=int)
    parser.add_argument("--output", required=True, type=Path)
    argumentos = parser.parse_args()
    semear(argumentos.tenant_id, argumentos.horas, argumentos.output)
