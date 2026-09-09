"""O lojista passa a ver o próprio estado — e a mandar em quem entra nos dados.

Duas coisas nesta migração, e as duas nascem do mesmo inventário.

**Diagnóstico.** Saúde de componentes, pendência de sincronização e sinal de
dispositivo já existiam — e nenhum deles chegava ao lojista. Ele não tinha como
responder "está tudo funcionando?" sem ligar para alguém, e é justamente quando
não está funcionando que ligar é mais difícil.

**Acesso assistido.** `assisted_support_grants` era pedido pela plataforma e
decidido pela plataforma. O dono dos dados não aparecia em nenhum dos dois lados:
não via o pedido, não aprovava, não revogava. Isso não era lacuna de tela — era
uma decisão de produto tomada por omissão, e o dono decidiu em 08/09/2026
corrigi-la: aprovação do responsável autorizado do tenant, com escopo,
expiração e revogação efetiva.

A consequência é deliberada: **toda autorização aprovada sem o tenant volta a
pendente.** Aprovar em massa para "não quebrar" seria manter valendo exatamente
o que esta sprint existe para acabar. Quem precisar de acesso pede de novo,
agora a quem tem de autorizar.

E **nada é apagado para isso**: quem aprovou e quando continuam gravados, e duas
colunas novas dizem quando e por que aquela aprovação perdeu validade. Limpar os
campos destruiria o histórico justamente na migração que existe para dar dono à
decisão.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "095_the_shop_sees_its_own_state"
down_revision: Union[str, None] = "094_what_the_shop_owes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Quem cortou o acesso é pergunta de auditoria, e não tinha resposta.
    op.add_column(
        "assisted_support_grants",
        sa.Column("revoked_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index(
        "ix_assisted_support_grants_revoked_by", "assisted_support_grants", ["revoked_by"]
    )

    # A política da tabela era `platform_only`: o dono dos dados não conseguia
    # nem **ler** a linha que fala do acesso aos dados dele. Não era só falta
    # de tela — era o banco dizendo que aquilo não era assunto dele.
    #
    # Ler e decidir passam a ser dele; criar continua não sendo: quem pede
    # acesso é quem quer entrar.
    op.execute(
        """
        CREATE POLICY assisted_support_grants_tenant_reads
        ON assisted_support_grants FOR SELECT
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY assisted_support_grants_tenant_decides
        ON assisted_support_grants FOR UPDATE
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        """
    )

    # Quando e por que uma aprovação anterior caiu. Sem estas duas colunas, a
    # única forma de invalidar era apagar `approved_by` e `approved_at` — e a
    # pergunta "quem tinha aprovado isto, e por que caiu?" ficaria sem resposta
    # exatamente na sprint que existe para dar dono a essa decisão.
    op.add_column(
        "assisted_support_grants",
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "assisted_support_grants",
        sa.Column("invalidated_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_assisted_support_grants_invalidated_at", "assisted_support_grants",
        ["invalidated_at"],
    )

    # O que foi aprovado sem o dono dos dados deixa de valer. **Nada é
    # apagado**: quem aprovou e quando continuam gravados, a linha volta a
    # pendente, e as duas colunas novas dizem o que houve com aquela aprovação.
    # É a mesma disciplina da reversão de baixa na UX-10 — desfazer é um
    # registro a mais, nunca um registro a menos.
    op.execute(
        """
        UPDATE assisted_support_grants
        SET status = 'PENDING',
            invalidated_at = now(),
            invalidated_reason = 'Aprovada pela plataforma antes de 08/09/2026, '
              'quando a autorização passou a exigir o responsável do tenant (UX-12). '
              'Precisa ser aprovada de novo por quem responde pela empresa.'
        WHERE status = 'APPROVED'
        """
    )

    op.execute(
        """
        INSERT INTO permissions (key, name, description, created_at)
        VALUES
          ('diagnostics.read', 'Ver o diagnóstico do sistema',
           'Conferir conexão, sincronização e situação dos equipamentos', now()),
          ('support.access.manage', 'Autorizar acesso do suporte',
           'Aprovar e revogar o acesso do suporte aos dados da empresa', now())
        ON CONFLICT (key) DO NOTHING
        """
    )
    # Diagnóstico é para quem opera a loja: quem descobre que algo não chegou é
    # quem está no balcão às sete da noite.
    op.execute(
        """
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'diagnostics.read'
        FROM role_profiles rp
        WHERE rp.is_system AND rp.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN', 'MANAGER')
        ON CONFLICT ON CONSTRAINT uq_role_profile_permission DO NOTHING
        """
    )
    # Autorizar quem entra nos dados da empresa não é tarefa de turno. Fica com
    # quem responde pela empresa — MANAGER não recebe.
    op.execute(
        """
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'support.access.manage'
        FROM role_profiles rp
        WHERE rp.is_system AND rp.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN')
        ON CONFLICT ON CONSTRAINT uq_role_profile_permission DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO module_contributions
          (id, capability_key, surface, contribution_key, label, group_key, route,
           permission_key, implementation_key, sort_order, metadata_json, is_active)
        VALUES (
          gen_random_uuid(), NULL, 'MANAGEMENT_NAV', 'diagnostics', 'Diagnóstico e suporte',
          'ADMINISTRACAO', '/manage/diagnostics', 'diagnostics.read', 'diagnostics', 95,
          '{"area": {"key": "ADMINISTRACAO", "label": "Administração", "order": 7},
            "description": "Veja se está tudo funcionando e quem tem acesso aos seus dados."}',
          true
        )
        ON CONFLICT ON CONSTRAINT uq_module_contribution_surface_key DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM module_contributions "
        "WHERE contribution_key = 'diagnostics' AND surface = 'MANAGEMENT_NAV'"
    )
    op.execute(
        "DELETE FROM role_profile_permissions "
        "WHERE permission_key IN ('diagnostics.read', 'support.access.manage')"
    )
    op.drop_index("ix_assisted_support_grants_invalidated_at", table_name="assisted_support_grants")
    op.drop_column("assisted_support_grants", "invalidated_reason")
    op.drop_column("assisted_support_grants", "invalidated_at")
    op.execute("DROP POLICY IF EXISTS assisted_support_grants_tenant_decides ON assisted_support_grants")
    op.execute("DROP POLICY IF EXISTS assisted_support_grants_tenant_reads ON assisted_support_grants")
    op.drop_index("ix_assisted_support_grants_revoked_by", table_name="assisted_support_grants")
    op.drop_column("assisted_support_grants", "revoked_by")
    op.execute(
        "DELETE FROM permissions WHERE key IN ('diagnostics.read', 'support.access.manage')"
    )
