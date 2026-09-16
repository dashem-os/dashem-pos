# Channel Hub — fundações, ativação e financiamento

Data: 10/09/2026. Planejamento autorizado pelo dono; não declara implementação,
homologação ou contratação de terceiros. Base inspecionada: 518e79a.

## Sequência no roadmap

1. S10.1: completar contrato e execução interna de pedidos/eventos, reaproveitando
   ChannelAdapter, MerchantConnection, ChannelInboxEvent e ExternalOrderMapping.
2. S13.2: completar publicação, disponibilidade e repasses com os modelos S13.
3. Conector oficial por canal/capacidade: autorização, contratos reais, sandbox,
   envio e recebimento efetivos. iFood é primeiro candidato, não escolha comercial
   obrigatória; 99Food depende de seus contratos, Rappi de investigação própria.
4. Homologação externa e piloto: provar cada capacidade antes de disponibilizá-la.
5. Ativação por tenant/unidade: plano elegível, autorização do estabelecimento,
   configuração, condições operacionais e monitoramento verificados.

S10.1/S13.2 podem avançar sem o bridge TEF, sem SDK de adquirente e sem credenciais
produtivas de marketplace. Construir e testar consome recursos internos; não
significa custo zero. Trabalho que demande contratação externa deve ter orçamento
e financiamento definidos antes da contratação. Não escolher preços nem incluir
capabilities em planos produtivos por inferência deste planejamento.

## Lacunas internas a fechar

Proposta técnica do S10.1, com os defeitos encontrados no código, invariantes,
testes e decisões pendentes: [proposta S10.1](proposta-s10-1-channel-hub.md).

- Separar contratos de autorização, pedidos, catálogo e logística por capacidades.
  Não criar um novo Order Engine nem obrigar todo adapter a suportar tudo.
- Ingressos oficiais validam assinatura conforme provedor e resolvem merchant para
  conexão autorizada no servidor. O webhook genérico atual não é o webhook iFood.
- Persistir antes de responder; distinguir confirmação HTTP, ACK externo e
  processamento concluído. Recuperar eventos após reinício sem depender de replay
  do provedor; definir política de dados pessoais no payload armazenado.
- Deduplicar eventos sem classificar toda atualização do mesmo pedido como
  duplicata. Tratar transições, eventos fora de ordem e cancelamentos.
- Provar criação/retomada de pedido e itens sob falha intermediária e concorrência.
- Normalizar mapeamentos e valores contratados no canal, incluindo complementos,
  descontos, frete e subsídios; preservar referências externas e origem financeira.
- Executar mensagens outbound e publicações: salvar PENDING não comprova entrega;
  registrar resultado, tentativa, reconciliação e intervenção com autoridade.
- Diferenciar disponibilidade desejada e confirmada; atraso externo não elimina
  a necessidade de reserva local e política para pedidos já recebidos.
- Manter pagamento online de marketplace distinto de TEF e de repasse financeiro.

## Local no produto

Gestão → Operação → Canais de Vendas, reutilizando ChannelHubWorkspace: Conexões,
Pedidos, Catálogo por canal e Repasses. Exibir situações por capacidade, última
sincronização e pendências com ações autorizadas. Diagnóstico técnico fica nos
detalhes; o lojista não deve preencher referência de cofre ou segredo de aplicação.

## Estados e comunicação comercial

| Estado | Evidência necessária | Comunicação permitida |
|---|---|---|
| Estrutura existente | Modelos, serviços e telas identificados | Temos uma base de gestão de canais; integrações específicas estão em desenvolvimento |
| Fundação validada | Gates S10.1/S13.2 aprovados, com limites das provas | Fundação de integração validada internamente; canais sujeitos a implementação/homologação |
| Conector em desenvolvimento | Escopo, orçamento e dependências registrados | Integração prevista, com condições e prazo acordados |
| Conector homologado | Evidência externa por capacidade | Integração disponível para ativação nas condições suportadas |
| Operacional na unidade | Plano, autorização, configuração e operação verificados | Canal ativo nesta unidade para as capacidades indicadas |

Contratação do plano pode viabilizar financiamento de desenvolvimento, licenças,
infraestrutura, equipamentos e homologação. Separar valores recorrentes,
implantação e desenvolvimento sob contratação, quando existirem. Orçar esses itens
com fornecedores; não presumir que toda API exige pagamento nem que acesso é
automático. Registrar responsável, dependências e critérios de aceite na proposta.

Não prometer “basta contratar para ligar” enquanto faltar engenharia interna ou
aprovação externa. Formulação atual: “O DASHEM POS já possui estrutura para gestão
de canais. A integração desejada será avaliada conforme o plano, o escopo de
implantação e as autorizações do provedor; desenvolvimento e custos adicionais,
quando necessários, serão apresentados antes da contratação.”

## Critérios de conclusão

Cada etapa registra implementação, provas executadas, limites e pendências.
Gates internos usam conector de referência; os efeitos no provedor são simulados,
mas persistência, rede, concorrência e recuperação locais devem ser exercitadas
de fato. CI não promove homologação. Contratação não promove conexão. Não alterar
migrações publicadas; conferir a cabeça vigente antes de criar nova migração.
