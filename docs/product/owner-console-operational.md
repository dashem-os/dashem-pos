# Console Owner operacional

## Princípio

O Console Owner é o plano de controle interno do Dashem. Ele não usa clientes,
métricas ou estados fictícios. Todo valor exibido deve vir do banco, de uma
verificação real ou aparecer explicitamente como **não instrumentado**.

O Platform Owner administra a relação SaaS com o tenant. Ele entrega o acesso
do administrador contratual, controla contrato, plano, limites, capabilities,
ciclo de vida e segurança. A criação e administração cotidiana de gerentes,
supervisores, atendentes, caixas e operadores pertence ao Tenant Administrator
no Dashem Gestão.

Cadastros de teste e pilotos usam as mesmas tabelas, validações, auditoria e
regras dos clientes comerciais. A diferença é a classificação do cliente e o
contrato, não um caminho alternativo no código.

## Ficha mestre do cliente

- Identidade comercial: nome fantasia, razão social, CNPJ, inscrições estadual
  e municipal e área de atuação.
- Contato empresarial: telefone, e-mail, site e observações internas.
- Responsáveis: contato principal e contatos adicionais, com cargo, telefone,
  e-mail e estado ativo.
- Estrutura: matriz e filiais com CNPJ/IE próprios quando aplicável, endereço
  completo, telefone, e-mail, fuso horário e estado operacional.
- Classificação: teste, piloto, cliente ou operação interna.
- Ciclo de vida: provisionando, avaliação, ativo, pausado, suspenso, cancelado
  ou arquivado.
- Contrato: plano persistido, vigência, limites de unidades, usuários e
  terminais, além das capacidades contratadas.

## Operação do tenant

- Criar e editar a ficha cadastral sem recriar o tenant técnico.
- Implantar matriz e filiais e ativá-las ou desativá-las.
- Entregar, reenviar, suspender ou revogar o acesso do administrador contratual.
- Suspender ou revogar acesso em uma ação de segurança/suporte explicitamente
  motivada e auditada, sem assumir a gestão cotidiana da equipe do cliente.
- Aumentar ou reduzir limites e capacidades por contrato.
- Pausar, suspender, cancelar ou arquivar sem apagar o histórico.
- Registrar toda mutação privilegiada em auditoria com ator, alvo, momento e
  correlação.

## Saúde e métricas

### Por cliente

- usuários convidados, ativos, suspensos e revogados;
- unidades e terminais ativos versus limites contratados;
- última atividade conhecida;
- vendas, sessões de caixa e falhas operacionais no período selecionado;
- eventos de outbox pendentes ou falhos;
- uso e estado de cada capacidade contratada.

### Plataforma

- API e backend;
- conexão e latência do PostgreSQL;
- fila/outbox e worker;
- Supabase Auth e entrega de e-mail;
- integrações de pagamento e fiscal;
- provedores de IA quando forem efetivamente configurados.

Gráficos só serão apresentados para séries temporais armazenadas. Um estado
instantâneo não deve ser disfarçado de histórico.

## Ordem de implementação

1. Ficha mestre, matriz/filiais, classificação, ciclo de vida e contrato.
2. Gestão auditada de acessos, limites e capacidades.
3. Métricas reais por tenant, com períodos e estados vazios honestos.
4. Registro de verificações e painel de saúde dos componentes da plataforma.
5. Alertas, incidentes, SLA/SLO e integrações de IA quando houver provedores.
