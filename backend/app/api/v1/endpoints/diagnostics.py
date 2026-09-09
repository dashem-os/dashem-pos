"""Diagnóstico do sistema e acesso assistido — pelo lado de quem tem a loja.

O contrato está em `docs/product/ux-12-diagnostico-e-suporte-contrato.md`.

**Parte 1 — está tudo funcionando?** Saúde de componentes, pendência de
sincronização e sinal de dispositivo já existiam no produto, todos do lado do
Owner. Nenhum chegava ao lojista, que não tinha como responder essa pergunta sem
ligar para alguém — e é justamente quando não está funcionando que ligar é mais
difícil.

Três regras que atravessam tudo aqui:

* **estado derivado, nunca gravado.** "Atrasado" é a idade do item mais antigo
  contra um limiar, calculada na hora. Uma coluna gravada precisaria de alguém
  virando linhas à meia-noite, e esse processo não existe;
* **silêncio não é saúde.** Se uma verificação falha, ela responde
  `NAO_VERIFICADO` — nunca verde por falta de resposta. Um diagnóstico que mente
  para o lado bom é pior do que nenhum;
* **nada de jargão.** Não se escreve "outbox" nem "backlog" para o lojista. A
  rota devolve número e idade; a tela escreve a frase;
* **cada frase afirma só o que a sua medição comprova.** Um `SELECT 1` prova que
  o banco respondeu, não que gravação funciona; a fila do servidor prova o que
  está nela, não o que ainda está num aparelho desconectado. Frase que promete
  mais do que a medida entrega é pior do que frase nenhuma, porque o lojista
  para de procurar.

**Parte 2 — quem entra nos meus dados.** `assisted_support_grants` era pedido
pela plataforma e decidido pela plataforma. O dono dos dados não via, não
aprovava e não revogava. Agora quem decide é ele.

Uma ressalva registrada de propósito: hoje **nenhuma rota de plataforma
atravessa para dentro da operação do tenant** — não há impersonação, e o console
do Owner não lê venda, cliente nem pagamento. A autorização governa o único
lugar em que a plataforma lê estado operacional do tenant hoje (o bloco de
operações do `control_workspace`) e é a porta única por onde qualquer acesso
assistido futuro tem de passar. Dizer mais do que isso seria vender uma proteção
maior do que a que existe.
"""

import uuid
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import func
from sqlmodel import Session, select, text

from app.core.context import TenantContext, get_tenant_context, resolve_actor
from app.core.database import get_session
from app.models.device import OperationalDevice, OperationalDeviceStatusEnum
from app.models.identity import User
from app.models.platform import AssistedSupportGrant, SupportGrantStatusEnum
from app.models.reliability import OutboxEvent, OutboxStatusEnum
from app.services import reliability_service

router = APIRouter()

#: A partir daqui, o que está esperando para sincronizar deixa de ser normal.
#: Sessenta segundos é o mesmo limiar que o painel da plataforma já usava — ter
#: dois números diferentes para a mesma pergunta é como as duas telas passam a
#: discordar sobre o mesmo sistema.
ATRASO_EM_SEGUNDOS = 60

#: Um terminal que não dá sinal há mais que isto não está no ar. É mais frouxo
#: que o intervalo de heartbeat de propósito: acusar a cada oscilação de rede
#: ensina o lojista a ignorar o aviso.
SILENCIO_DO_APARELHO_EM_MINUTOS = 15

Situacao = Literal["SAUDAVEL", "ATENCAO", "PARADO", "NAO_VERIFICADO"]


class Verificacao(BaseModel):
    chave: str
    titulo: str
    situacao: Situacao
    #: A frase que a tela mostra. Vem pronta para não haver duas redações da
    #: mesma resposta em lugares diferentes.
    resumo: str
    detalhes: dict = {}


class AparelhoNoDiagnostico(BaseModel):
    id: uuid.UUID
    nome: str
    tipo: str
    situacao: Situacao
    visto_em: Optional[datetime] = None
    minutos_sem_sinal: Optional[int] = None


class Diagnostico(BaseModel):
    verificado_em: datetime
    situacao_geral: Situacao
    verificacoes: List[Verificacao]
    aparelhos: List[AparelhoNoDiagnostico]


class AcessoAssistido(BaseModel):
    id: uuid.UUID
    situacao: SupportGrantStatusEnum
    #: Derivada: a hora contra o prazo. Não há coluna "expirado", porque ela
    #: exigiria alguém virando linhas quando o prazo vence.
    expirado: bool
    #: `True` só quando a autorização realmente vale agora.
    vale_agora: bool
    escopo: List[str]
    motivo: str
    #: **Quem** está pedindo. Sem isto, a tela prometia dizer quem tem acesso
    #: aos dados e entregava só o motivo — e a autorização era anônima.
    solicitante: str
    solicitante_email: Optional[str] = None
    expira_em: datetime
    aprovado_em: Optional[datetime] = None
    revogado_em: Optional[datetime] = None
    solicitado_em: datetime
    #: Quando e por que uma aprovação anterior deixou de valer. A migração 095
    #: preenche estes campos em vez de apagar quem aprovou.
    invalidada_em: Optional[datetime] = None
    invalidada_porque: Optional[str] = None


class DecisaoDeAcesso(BaseModel):
    model_config = ConfigDict(extra="forbid")
    motivo: str = PydanticField(min_length=3)


# ---------------------------------------------------------------------------
# A porta única do acesso assistido
# ---------------------------------------------------------------------------


def autorizacao_assistida_valida(
    session: Session,
    tenant_id: uuid.UUID,
    profissional_id: uuid.UUID,
    escopo: Optional[str] = None,
) -> Optional[AssistedSupportGrant]:
    """A autorização que vale **agora**, para **esta pessoa**, neste tenant.

    Esta é a porta. Qualquer caminho pelo qual a plataforma venha a ler dado
    operacional de um tenant tem de passar por aqui — e é isto que torna a
    revogação efetiva em vez de decorativa: revogar muda a linha, e a próxima
    leitura já não encontra autorização.

    **`profissional_id` não é opcional, e é o ponto principal.** A primeira
    versão conferia tenant, situação, prazo e escopo — e não conferia quem
    estava lendo. Uma autorização dada a uma pessoa abria a porta para qualquer
    outra que alcançasse o console, enquanto a tela do lojista dizia
    "quem tem acesso aos seus dados". Autorizar é sempre nominal: quem pediu é
    quem entra.

    Autorizar uma equipe inteira seria outra coisa, teria de estar escrita no
    pedido, e é decisão do dono do produto — não se deduz do silêncio.

    Expiração é conferida aqui, não gravada em lugar nenhum: a linha continua
    `APPROVED` e simplesmente deixa de valer quando o prazo passa.
    """
    agora = datetime.utcnow()
    consulta = select(AssistedSupportGrant).where(
        AssistedSupportGrant.tenant_id == tenant_id,
        AssistedSupportGrant.requested_by == profissional_id,
        AssistedSupportGrant.status == SupportGrantStatusEnum.APPROVED,
        AssistedSupportGrant.expires_at > agora,
    )
    for concessao in session.exec(consulta.order_by(AssistedSupportGrant.expires_at.desc())).all():
        if escopo is None or escopo in (concessao.scope or []):
            return concessao
    return None


def _quem_pediu(session: Session, concessao: AssistedSupportGrant) -> tuple[str, Optional[str]]:
    """O nome e o e-mail de quem pediu.

    A tela promete responder "quem tem acesso aos seus dados", e uma linha sem
    nome não responde isso. Se o cadastro do profissional sumir, a tela diz que
    não sabe — em vez de calar e parecer que não havia ninguém.
    """
    pessoa = session.get(User, concessao.requested_by)
    if pessoa is None:
        return "Profissional não identificado", None
    return (pessoa.full_name or pessoa.email or "Profissional sem nome"), pessoa.email


def _ler_acesso(session: Session, concessao: AssistedSupportGrant) -> AcessoAssistido:
    agora = datetime.utcnow()
    expirado = concessao.expires_at <= agora
    nome, email = _quem_pediu(session, concessao)
    return AcessoAssistido(
        id=concessao.id, situacao=concessao.status, expirado=expirado,
        vale_agora=concessao.status == SupportGrantStatusEnum.APPROVED and not expirado,
        escopo=list(concessao.scope or []), motivo=concessao.reason,
        solicitante=nome, solicitante_email=email,
        expira_em=concessao.expires_at, aprovado_em=concessao.approved_at,
        revogado_em=concessao.revoked_at, solicitado_em=concessao.created_at,
        invalidada_em=concessao.invalidated_at,
        invalidada_porque=concessao.invalidated_reason,
    )


# ---------------------------------------------------------------------------
# Parte 1 — está tudo funcionando?
# ---------------------------------------------------------------------------


def _minutos(desde: datetime, ate: datetime) -> int:
    return int((ate - desde).total_seconds() // 60)


def _pior(situacoes: List[Situacao]) -> Situacao:
    """A situação geral é a pior das partes.

    Média de saúde esconde exatamente o que precisa de decisão: dois
    componentes saudáveis e um parado não são "quase saudável".
    """
    for grave in ("PARADO", "NAO_VERIFICADO", "ATENCAO"):
        if grave in situacoes:
            return grave  # type: ignore[return-value]
    return "SAUDAVEL"


@router.get("", response_model=Diagnostico)
def diagnostico(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    agora = datetime.utcnow()
    verificacoes: List[Verificacao] = []

    # --- o servidor respondeu, e é por isso que esta linha existe -----------
    verificacoes.append(Verificacao(
        chave="servidor", titulo="Conexão com o sistema", situacao="SAUDAVEL",
        resumo="O sistema respondeu agora.",
    ))

    # --- o banco, medido de verdade ----------------------------------------
    try:
        inicio = datetime.utcnow()
        session.exec(text("SELECT 1")).one()
        demora = int((datetime.utcnow() - inicio).total_seconds() * 1000)
        verificacoes.append(Verificacao(
            chave="dados", titulo="Conexão com o banco", situacao="SAUDAVEL",
            # Um `SELECT 1` prova que o banco respondeu. Ele **não** prova que
            # gravação funciona, nem que os seus dados estão íntegros — e dizer
            # "leitura e gravação respondendo normalmente" era afirmar duas
            # coisas com a prova de uma.
            resumo="Conexão com o banco respondendo.",
            detalhes={"resposta_ms": demora},
        ))
    except Exception as falha:  # pragma: no cover - caminho de indisponibilidade
        verificacoes.append(Verificacao(
            chave="dados", titulo="Conexão com o banco", situacao="NAO_VERIFICADO",
            resumo="Não foi possível verificar agora.",
            detalhes={"erro": str(falha)[:200]},
        ))

    # --- o que está esperando para sincronizar ------------------------------
    try:
        pendentes = (
            select(OutboxEvent)
            .where(
                OutboxEvent.tenant_id == context.tenant_id,
                OutboxEvent.status.in_(
                    (OutboxStatusEnum.PENDING, OutboxStatusEnum.PROCESSING)
                ),
            )
        )
        quantos = int(session.exec(
            select(func.count()).select_from(pendentes.subquery())
        ).one() or 0)
        mais_antigo = session.exec(
            select(func.min(OutboxEvent.created_at)).where(
                OutboxEvent.tenant_id == context.tenant_id,
                OutboxEvent.status.in_(
                    (OutboxStatusEnum.PENDING, OutboxStatusEnum.PROCESSING)
                ),
            )
        ).one()
        falhados = int(session.exec(
            select(func.count()).select_from(
                select(OutboxEvent).where(
                    OutboxEvent.tenant_id == context.tenant_id,
                    OutboxEvent.status == OutboxStatusEnum.FAILED,
                ).subquery()
            )
        ).one() or 0)

        idade = (agora - mais_antigo).total_seconds() if mais_antigo else 0
        # Esta verificação olha a **fila do servidor**, e é só isso que ela pode
        # afirmar. O que ainda estiver num aparelho desconectado não passou por
        # aqui e não seria contado — então "tudo o que você registrou já foi
        # enviado" prometia uma garantia que a medição não dá.
        if falhados:
            situacao: Situacao = "PARADO"
            resumo = (
                f"{falhados} {'envio' if falhados == 1 else 'envios'} "
                "falharam na fila do servidor. Fale com o suporte."
            )
        elif idade > ATRASO_EM_SEGUNDOS:
            situacao = "ATENCAO"
            minutos = max(1, int(idade // 60))
            resumo = (
                f"{quantos} {'envio parado' if quantos == 1 else 'envios parados'} "
                f"na fila do servidor, o mais antigo há {minutos} "
                f"{'minuto' if minutos == 1 else 'minutos'}."
            )
        elif quantos:
            situacao = "SAUDAVEL"
            resumo = (
                f"{quantos} {'envio saindo' if quantos == 1 else 'envios saindo'} "
                "da fila do servidor agora."
            )
        else:
            situacao = "SAUDAVEL"
            resumo = "Nenhum envio pendente na fila do servidor."
        verificacoes.append(Verificacao(
            chave="sincronizacao", titulo="Fila de envios do servidor", situacao=situacao,
            resumo=resumo,
            detalhes={"esperando": quantos, "com_falha": falhados,
                      "espera_em_segundos": int(idade),
                      # Dito no dado, para nenhuma tela concluir mais do que a
                      # medição permite.
                      "abrange": "fila do servidor; não alcança aparelho desconectado"},
        ))
    except Exception as falha:  # pragma: no cover - caminho de indisponibilidade
        verificacoes.append(Verificacao(
            chave="sincronizacao", titulo="O que você registrou", situacao="NAO_VERIFICADO",
            resumo="Não foi possível verificar agora.",
            detalhes={"erro": str(falha)[:200]},
        ))

    # --- os aparelhos -------------------------------------------------------
    aparelhos: List[AparelhoNoDiagnostico] = []
    consulta = select(OperationalDevice).where(
        OperationalDevice.tenant_id == context.tenant_id,
        OperationalDevice.status != OperationalDeviceStatusEnum.REVOKED,
    )
    if context.store_id:
        consulta = consulta.where(OperationalDevice.store_id == context.store_id)
    for aparelho in session.exec(consulta.order_by(OperationalDevice.name)).all():
        if aparelho.last_seen_at is None:
            aparelhos.append(AparelhoNoDiagnostico(
                id=aparelho.id, nome=aparelho.name, tipo=aparelho.device_type.value,
                situacao="NAO_VERIFICADO", visto_em=None, minutos_sem_sinal=None,
            ))
            continue
        calado = _minutos(aparelho.last_seen_at, agora)
        aparelhos.append(AparelhoNoDiagnostico(
            id=aparelho.id, nome=aparelho.name, tipo=aparelho.device_type.value,
            situacao="PARADO" if calado > SILENCIO_DO_APARELHO_EM_MINUTOS else "SAUDAVEL",
            visto_em=aparelho.last_seen_at, minutos_sem_sinal=calado,
        ))

    if aparelhos:
        verificacoes.append(Verificacao(
            chave="aparelhos", titulo="Seus equipamentos",
            situacao=_pior([a.situacao for a in aparelhos]),
            resumo=_resumo_dos_aparelhos(aparelhos),
            detalhes={"total": len(aparelhos)},
        ))

    return Diagnostico(
        verificado_em=agora,
        situacao_geral=_pior([v.situacao for v in verificacoes]),
        verificacoes=verificacoes, aparelhos=aparelhos,
    )


def _resumo_dos_aparelhos(aparelhos: List[AparelhoNoDiagnostico]) -> str:
    """O que se sabe é quando cada aparelho **deu sinal pela última vez**.

    "Respondendo" seria afirmar que ele está no ar agora, e ninguém perguntou a
    ele: o que existe é o último sinal registrado.
    """
    parados = [a for a in aparelhos if a.situacao == "PARADO"]
    mudos = [a for a in aparelhos if a.situacao == "NAO_VERIFICADO"]
    if parados:
        nomes = ", ".join(a.nome for a in parados[:3])
        return f"Sem sinal recente: {nomes}." if len(parados) <= 3 else (
            f"{len(parados)} equipamentos sem sinal recente."
        )
    if mudos and len(mudos) == len(aparelhos):
        return "Nenhum equipamento deu sinal ainda."
    return (
        f"{len(aparelhos)} {'equipamento deu sinal' if len(aparelhos) == 1 else 'equipamentos deram sinal'} "
        f"nos últimos {SILENCIO_DO_APARELHO_EM_MINUTOS} minutos."
    )


# ---------------------------------------------------------------------------
# Parte 2 — quem entra nos meus dados
# ---------------------------------------------------------------------------


@router.get("/acesso-assistido", response_model=List[AcessoAssistido])
def listar_acessos(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    concessoes = session.exec(
        select(AssistedSupportGrant)
        .where(AssistedSupportGrant.tenant_id == context.tenant_id)
        .order_by(AssistedSupportGrant.created_at.desc())
    ).all()
    return [_ler_acesso(session, item) for item in concessoes]


def _usuario_real(session: Session, actor_id: uuid.UUID) -> Optional[uuid.UUID]:
    """O identificador só vai para a coluna se ele **for** um usuário.

    `approved_by` e `revoked_by` apontam para `users`, e apontar para uma linha
    que não existe é mentira com integridade referencial por cima. No modo de
    autenticação desligado — que só a suíte usa — o ator é um identificador
    sintético; ali a coluna fica vazia e o evento de auditoria continua
    guardando quem agiu, porque ele não tem essa amarra.

    Em operação autenticada quem aprova está logado, então a coluna sempre tem
    dono.
    """
    return actor_id if session.get(User, actor_id) else None


def _do_tenant(
    session: Session, context: TenantContext, grant_id: uuid.UUID,
) -> AssistedSupportGrant:
    concessao = session.exec(
        select(AssistedSupportGrant)
        .where(
            AssistedSupportGrant.id == grant_id,
            AssistedSupportGrant.tenant_id == context.tenant_id,
        )
        .with_for_update()
    ).first()
    if not concessao:
        raise HTTPException(status_code=404, detail="Autorização não encontrada.")
    return concessao


@router.post("/acesso-assistido/{grant_id}/aprovacao", response_model=AcessoAssistido)
def aprovar_acesso(
    grant_id: uuid.UUID,
    data: DecisaoDeAcesso,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    """Só quem responde pela empresa autoriza alguém a entrar nos dados dela."""
    concessao = _do_tenant(session, context, grant_id)
    if concessao.status != SupportGrantStatusEnum.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta autorização já foi decidida. Recarregue para ver como ficou.",
        )
    if concessao.expires_at <= datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "O prazo deste pedido já passou. Peça ao suporte um novo pedido, "
                "com prazo válido."
            ),
        )
    actor_id = resolve_actor(context)
    concessao.status = SupportGrantStatusEnum.APPROVED
    concessao.approved_by = _usuario_real(session, actor_id)
    concessao.approved_at = datetime.utcnow()
    # A decisão nova é a que vale: a marca da invalidação anterior sai, e o
    # histórico de que ela existiu fica na auditoria.
    concessao.invalidated_at = None
    concessao.invalidated_reason = None
    session.add(concessao)
    reliability_service.write_audit_and_outbox(
        session, tenant_id=context.tenant_id, store_id=None, actor_id=actor_id,
        action="tenant.support_access.approved", target=f"support:{concessao.id}",
        audit_payload={"scope": list(concessao.scope or []), "motivo": data.motivo,
                       "expira_em": concessao.expires_at.isoformat()},
        aggregate_type="assisted_support_grant", aggregate_id=str(concessao.id),
        event_type="tenant.support_access.approved",
        outbox_payload={"scope": list(concessao.scope or []),
                        "expira_em": concessao.expires_at.isoformat()},
    )
    session.commit()
    session.refresh(concessao)
    return _ler_acesso(session, concessao)


@router.post("/acesso-assistido/{grant_id}/revogacao", response_model=AcessoAssistido)
def revogar_acesso(
    grant_id: uuid.UUID,
    data: DecisaoDeAcesso,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    """Cortar tem efeito imediato: a próxima leitura já não acha autorização.

    Um pedido ainda pendente também se recusa por aqui — negar é revogar antes
    de valer, e obrigar a pessoa a aprovar para depois cortar seria pedir que
    ela abrisse a porta para poder fechá-la.
    """
    concessao = _do_tenant(session, context, grant_id)
    if concessao.status == SupportGrantStatusEnum.REVOKED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este acesso já estava revogado.",
        )
    actor_id = resolve_actor(context)
    era = concessao.status
    concessao.status = SupportGrantStatusEnum.REVOKED
    concessao.revoked_at = datetime.utcnow()
    concessao.revoked_by = _usuario_real(session, actor_id)
    session.add(concessao)
    reliability_service.write_audit_and_outbox(
        session, tenant_id=context.tenant_id, store_id=None, actor_id=actor_id,
        action="tenant.support_access.revoked", target=f"support:{concessao.id}",
        audit_payload={"de": era.value, "motivo": data.motivo,
                       "scope": list(concessao.scope or [])},
        aggregate_type="assisted_support_grant", aggregate_id=str(concessao.id),
        event_type="tenant.support_access.revoked",
        outbox_payload={"de": era.value, "scope": list(concessao.scope or [])},
    )
    session.commit()
    session.refresh(concessao)
    return _ler_acesso(session, concessao)
