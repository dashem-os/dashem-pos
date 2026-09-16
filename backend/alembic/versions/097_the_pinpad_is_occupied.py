"""O comando chega à maquininha, e o terminal diz quando está ocupado.

O servidor sabia pedir uma cobrança e sabia receber a resposta. Ele não sabia
entregar o pedido: `BridgeQueuedAdapter.start` gravava `bridge_command: START`
em `sanitized_payload` e ninguém lia esse campo. Com adquirente contratado e
pinpad na mão, nenhuma cobrança sairia.

Duas tabelas, e a segunda é a que guarda dinheiro.

`tef_bridge_commands` é a fila por terminal. O `id` é a identidade estável do
comando: reenviar é repetir a mesma identidade, nunca criar comando novo, porque
é por ela que o bridge deduplica antes de acionar o pinpad.

`tef_terminal_occupancy` é a ocupação, e ela fala da **operação financeira**, não
do comando. Um comando pode morrer no fio enquanto a cobrança segue incerta — e é
exatamente aí que o terminal não pode aceitar outra. Por isso o cadeado é o índice
parcial sobre `released_at IS NULL`, e não a chave primária: com o terminal como
chave, preencher `released_at` deixava a linha ocupando a chave e travava o caixa
para sempre.

A liberação confere a operação proprietária: a transação **e** o que foi pedido a
ela. Sem essa conferência, um resultado tardio da cobrança antiga soltaria o
terminal já ocupado pela cobrança seguinte — e, como o estorno anda sobre a
cobrança que reverte e divide a transação com ela (ADR-030), uma confirmação
repetida da cobrança soltaria o terminal no meio do estorno.

Expiração de lease, tentativas esgotadas e resposta desconhecida não liberam
ocupação: tempo não prova ausência de cobrança. E consulta dizendo "não executou"
também não basta quando um executor anterior ainda pode acionar o SDK — por isso
`neutralization` fica na linha, e sem ela a ocupação não sai.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "097_the_pinpad_is_occupied"
down_revision: Union[str, None] = "096_the_grant_keeps_its_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PLATFORM = "current_setting('app.platform_access', true) = 'true'"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
STORE = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
SCOPE = (
    f"({PLATFORM}) OR (({TENANT}) AND "
    f"(nullif(current_setting('app.store_id', true), '') IS NULL OR {STORE}))"
)


def upgrade() -> None:
    op.create_table(
        "tef_bridge_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("bridge_terminal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tef_bridge_terminals.id"), nullable=False),
        sa.Column("provider_transaction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("provider_transactions.id"), nullable=False),
        sa.Column("command_type", sa.String(length=50), nullable=False),
        sa.Column("command_class", sa.String(length=50), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("delivery_status", sa.String(length=50), nullable=False),
        sa.Column("installation_epoch", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("acked_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("closed_reason", sa.String(length=80), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("bridge_terminal_id", "sequence", name="uq_bridge_command_terminal_sequence"),
    )
    for coluna in ("tenant_id", "store_id", "bridge_terminal_id", "provider_transaction_id",
                   "command_type", "command_class", "delivery_status", "available_at", "created_at"):
        op.create_index(f"ix_tef_bridge_commands_{coluna}", "tef_bridge_commands", [coluna])

    # O caminho quente da entrega: o que está pronto para este terminal, na ordem.
    op.create_index(
        "ix_tef_bridge_commands_claimable", "tef_bridge_commands",
        ["bridge_terminal_id", "command_class", "sequence"],
        postgresql_where=sa.text("delivery_status IN ('PENDING', 'LEASED')"),
    )

    op.create_table(
        "tef_terminal_occupancy",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("bridge_terminal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tef_bridge_terminals.id"), nullable=False),
        sa.Column("provider_transaction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("provider_transactions.id"), nullable=False),
        # Qual operação ocupa: cobrança ou estorno da mesma transação.
        sa.Column("operation", sa.String(length=50), nullable=False),
        # O que se sabe sobre o dinheiro. A ocupação existe enquanto isto não
        # estiver provado; o estado do comando no fio não entra nesta conta.
        sa.Column("financial_resolution", sa.String(length=50), nullable=False),
        # Sem neutralização registrada do executor anterior, consulta dizendo
        # "não executou" não solta o terminal: ela descreve o passado, e o
        # processo suspenso é um fato do futuro.
        sa.Column("neutralization", sa.String(length=50), nullable=True),
        # Sob qual instalação esta ocupação nasceu. Se o terminal trocou de
        # instalação depois, o executor de antes tem armazenamento local próprio
        # e a deduplicação dele não nos alcança: aí exige-se neutralização.
        sa.Column("acquired_epoch", sa.Integer(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("released_reason", sa.String(length=120), nullable=True),
        sa.Column("released_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    for coluna in ("tenant_id", "store_id", "bridge_terminal_id",
                   "provider_transaction_id", "financial_resolution", "acquired_at"):
        op.create_index(f"ix_tef_terminal_occupancy_{coluna}", "tef_terminal_occupancy", [coluna])

    # O cadeado. Uma ocupação viva por terminal; o histórico fica.
    op.create_index(
        "uq_terminal_occupied", "tef_terminal_occupancy",
        ["bridge_terminal_id"], unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )

    # O que já estava incerto antes desta migração continua incerto depois dela.
    # Uma cobrança que saiu para o bridge e nunca teve resposta ocupa o terminal
    # desde já; sem esta linha, a primeira cobrança nova passaria por cima dela.
    # Se o terminal carrega mais de uma — o estado que este invariante passa a
    # impedir —, a mais recente ocupa, e as outras seguem visíveis como
    # transações a reconciliar (S25.1). Não se escolhe por elas.
    op.execute("SELECT set_config('app.platform_access', 'true', true)")
    op.execute("""
        INSERT INTO tef_terminal_occupancy (
            id, tenant_id, store_id, bridge_terminal_id, provider_transaction_id,
            operation, financial_resolution, acquired_epoch, acquired_at
        )
        SELECT DISTINCT ON (pt.bridge_terminal_id)
               gen_random_uuid(), pt.tenant_id, pt.store_id, pt.bridge_terminal_id, pt.id,
               'START', 'INCERTA', 0, (now() AT TIME ZONE 'utc')
          FROM provider_transactions pt
         WHERE pt.bridge_terminal_id IS NOT NULL
           AND pt.status IN ('CREATED', 'PROCESSING', 'UNKNOWN')
         ORDER BY pt.bridge_terminal_id, pt.created_at DESC
    """)
    # `set_config(..., true)` vale até o fim da transação, e o Alembic aplica as
    # migrações de uma execução numa transação só: a visibilidade de plataforma
    # não segue viva para o que vier depois.
    op.execute("SELECT set_config('app.platform_access', 'false', true)")

    # Presença e prontidão são coisas diferentes: `last_seen_at` diz que o bridge
    # falou, `device_state` diz o que ele viu no pinpad. Um bridge de pé com a
    # maquininha desconectada responde ao long-poll e não cobra nada.
    op.add_column("tef_bridge_terminals", sa.Column("last_seen_at", sa.DateTime(), nullable=True))
    op.add_column("tef_bridge_terminals", sa.Column("device_state", sa.String(length=50), nullable=True))
    op.add_column("tef_bridge_terminals", sa.Column("active_installation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("tef_bridge_terminals", sa.Column("installation_epoch", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_tef_bridge_terminals_last_seen_at", "tef_bridge_terminals", ["last_seen_at"])
    op.create_index("ix_tef_bridge_terminals_active_installation_id", "tef_bridge_terminals", ["active_installation_id"])

    for tabela in ("tef_bridge_commands", "tef_terminal_occupancy"):
        op.execute(f'ALTER TABLE "{tabela}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{tabela}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY {tabela}_isolation ON "{tabela}" FOR ALL '
            f"USING ({SCOPE}) WITH CHECK ({SCOPE})"
        )


def downgrade() -> None:
    for tabela in ("tef_bridge_commands", "tef_terminal_occupancy"):
        op.execute(f'DROP POLICY IF EXISTS {tabela}_isolation ON "{tabela}"')
    op.drop_index("ix_tef_bridge_terminals_active_installation_id", table_name="tef_bridge_terminals")
    op.drop_index("ix_tef_bridge_terminals_last_seen_at", table_name="tef_bridge_terminals")
    op.drop_column("tef_bridge_terminals", "installation_epoch")
    op.drop_column("tef_bridge_terminals", "active_installation_id")
    op.drop_column("tef_bridge_terminals", "device_state")
    op.drop_column("tef_bridge_terminals", "last_seen_at")
    op.drop_table("tef_terminal_occupancy")
    op.drop_table("tef_bridge_commands")
