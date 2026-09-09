# Gestão e PDV — sprints de implementação da experiência

Status: UX-00 a UX-08 executadas em 08/09/2026. **Não é "fundação fechada"**: há entregas publicadas e verdes, e continuam abertas as lacunas de homologação nomeadas na [UX-08](../quality/ux-08-homologacao-2026-09-08.md) — dois destinos nunca percorridos, catálogo volumoso não exercitado, concorrência de duas estações não validada pela tela. UX-13, UX-09 e UX-10 executadas em 08/09/2026. UX-12 executada em 09/09/2026, e **continua aberta em dois pontos**: o canal real de suporte ainda não foi definido, e o caminho de emergência ficou fora da primeira entrega por decisão do dono. **UX-11 é a única aguardando regras de cálculo** — não é a única aberta. Os **dois destinos nunca percorridos saíram da lista** em 09/09/2026 — [Ambientes e Mesas e Provedores de pagamento](../quality/homologacao-destinos-nunca-percorridos-2026-09-09.md), com um defeito real encontrado no caminho. Continuam abertas: catálogo volumoso não exercitado, concorrência de duas estações não validada, estado "em processamento" do TEF sem tela, conceder autoridade a um operador e vê-lo agir sozinho, e **transação TEF real com provedor** — nomeada agora, porque configurar e simular não a comprovam.
Origem: direção explícita do usuário nesta conversa, em 07/09/2026.
Plano visual: [evolução de UI/UX](ui-ux-evolution-plan.md).
Referências de arquitetura para execução: [ADR-034 — hierarquia da interface e redução do esforço do operador](../architecture/adr-034-interface-hierarchy.md) e [ADR-032 — disponibilidade prometida e compromisso de estoque](../architecture/adr-032-available-to-promise.md).
Aplicação: ADR-034 orienta Gestão e PDV em todas as sprints; ADR-032 é referência de domínio para UX-04, UX-06 e UX-07. Seu núcleo de balcão está publicado em `main` desde 07/09/2026: reserva na inclusão, disponível, recusa antes do pagamento, liberação no cancelamento, consumo na conclusão e validade de 30 min do carrinho. A homologação em duas estações foi registrada em `a42e578`, também em 07/09/2026; busca e grade já leem disponível. Continuam pendentes reservas de comanda/pedido, `on_order`, avisos sobre ATP projetado e extensões de leitura/expiração, conforme "Situação da implementação" no ADR. A etapa 3.0 do plano de estoque já foi entregue em `45ee54e`, com percurso em Gestão e PDV. Essas entregas são a base existente desta trilha, sem declarar as sprints UX concluídas.
Integração: [trilha da Gestão](tenant-management-correction-sprints.md), [estoque](inventory-operational-correction-plan.md) e [roadmap V2](roadmap-commerce-os-v2.md).

Esta trilha usa o prefixo UX para não renumerar sprints históricas nem declarar concluídos gates anteriores. A navegação abaixo substitui a proposta de sidebar persistente do plano inicial. Gestão vem primeiro, PDV permanece como entrega explícita.

## Contrato de navegação solicitado

1. A entrada da Gestão apresenta sidebar com exatamente as sete áreas, na ordem abaixo, para o perfil com acesso completo. Não criar uma oitava aba “Visão geral”. O conteúdo inicial pode conter o resumo gerencial autorizado existente.
2. Ao escolher uma área, ocultar a sidebar e ocupar a área útil com cards das funcionalidades daquela área. Sem expansão infinita de submenus na lateral.
3. O topo global dos hubs e módulos tem apenas duas ações: **Menu principal** (retorna às sete áreas) e **Sair**. Nome da área e unidade podem aparecer como texto de contexto. Ações de negócio pertencem ao conteúdo.
4. Ao abrir um card, mostrar o módulo em largura útil. No conteúdo, oferecer “Voltar para Mercadorias”, por exemplo. Esse retorno leva ao hub; “Menu principal” leva à entrada. Nunca usar um único “Voltar” ambíguo.
5. Usar histórico de navegação real: voltar/avançar do navegador, atualização e link direto reconstituem área e módulo. Preservar filtros e posição ao retornar. Compatibilizar os links atuais `?module=...`.
6. Foco segue para o título após navegação e retorna ao card ao voltar. No menu mobile, fechar devolve foco ao acionador. Confirmar descarte somente quando houver alterações não salvas.
7. Autorizações continuam vindo das contribuições/capabilities e do servidor. O mapa completo possui sete áreas; perfis restritos veem somente destinos autorizados. Não criar acesso ou conteúdo vazio para completar sete itens.

## Mapa exato e destinos

Correções apenas de escrita: “Estoques”, “Contas a pagar”, “Comissões e gorjetas”, “Plano e solicitações”. O card do sortimento chama-se “Catálogos”, e “Cardápios” para quem contrata `FOOD_SERVICE`: a 086 trocou o rótulo para todos, e a 088 corrigiu isso movendo a palavra do nicho para `metadata_json.label_variants` da própria contribuição. Padaria vê cardápio; revendedora de beleza vê catálogo. “Sortimento” continua sendo o nome do agregado no código, no banco e no domínio — a tela fala a língua de quem vende, o modelo fala a sua. Descrição explica a tarefa.

| Ordem / área | Card, na ordem pedida | Destino observado ou trabalho necessário | Descrição curta proposta |
|---|---|---|---|
| 1 Operação | Vendas | `SalesHistory` | Consulte vendas e acompanhe pagamentos. |
| | Caixas | `CashManager` | Confira aberturas, movimentos e fechamentos. |
| | Canais de Vendas | `ChannelHubWorkspace` | Acompanhe pedidos dos seus canais. |
| 2 Mercadorias | Produtos e Preços | `CatalogManager` | Cadastre produtos e atualize preços. |
| | Cardápios | `AssortmentManager` | Escolha os produtos vendidos em cada canal. |
| | Categorias | `CategoryManager` | Organize produtos para encontrá-los facilmente. |
| | Estoques | `InventoryManager` | Receba mercadorias e confira quantidades. |
| 3 Estrutura | Ambientes e Mesas | `ServiceSetupManager` | Organize os espaços e mesas do atendimento. |
| | Terminais e Dispositivos | `DeviceManager` | Gerencie os equipamentos da operação. |
| 4 Pessoas | Funcionários e Acessos | `TeamManager` | Cadastre a equipe e defina acessos. |
| 5 Relacionamento | Clientes | `CustomerManager` | Encontre e atualize seus clientes. |
| | Fornecedores | Não localizado como módulo gerencial na inspeção inicial | Organize quem fornece suas mercadorias. |
| 6 Financeiro | Crediário e Recebíveis | `ReceivablesManager` | Acompanhe valores que seus clientes devem. |
| | Contas a pagar | Não localizado como módulo gerencial na inspeção inicial | Acompanhe compromissos e vencimentos. |
| | Comissões e gorjetas | Não localizado como módulo gerencial na inspeção inicial | Confira valores destinados à equipe. |
| 7 Administração | Plano e solicitações | `TenantPlanWorkspace` | Consulte seu plano e acompanhe solicitações. |
| | Manutenção | Escopo funcional ainda a definir; não confundir com administração da plataforma | Descrição depende do escopo confirmado. |

Existência de componente não significa jornada homologada. A comissão de marketplace encontrada no código não implementa comissão de funcionário.

Destinos existentes fora da lista: manter `DashboardBI` no conteúdo inicial, respeitando autorização. Preservar `PaymentProviderManager` como configuração de pagamentos acessível dentro de Financeiro/Crediário e Recebíveis e por link direto autorizado; não eliminar funcionalidade nem criar oitava área. “Validar no PDV” passa para o conteúdo de Operação/Vendas, conservando identidade gerencial e auditoria.

Cards têm ícone consistente, título concreto, uma frase de tarefa e área inteira acionável por teclado/toque. Quantidade ou alerta só aparece com dado confiável e relevante; evitar cards altos, parágrafos e indicadores decorativos. Grade adaptável de 1 a 3 colunas conforme espaço; mesmo com um card, não esticá-lo para preencher a tela. Ordem fixa, sem reorganização automática.

## Ordem e dependências

UX-00 → UX-01 → UX-02 → UX-03 → UX-04 → UX-05 → UX-06 → UX-07 → UX-08.
UX-09 a UX-12 são entregas funcionais adicionais: detalhamento pode começar após UX-00; implementação após os respectivos contratos e dependências. Não são condição para melhorar módulos existentes nem estão implicitamente concluídas ao entregar cards.

### UX-00 — Inventário e baseline

Entregar inventário de rotas, contribuições, permissões, componentes, endpoints e estados atuais; reproduzir os principais atritos da Gestão e PDV. Conferir AGENTS.md aplicável antes de editar. Registrar screenshots desktop, tela baixa e mobile, versão/commit e pendências reais do CI.

Aceite: todos os destinos da tabela classificados como existente, parcial ou ausente com evidência; links legados inventariados; gates de estoque/pagamento associados às sprints afetadas. Não corrigir CI de outro projeto a partir das capturas anexadas. Bloqueios de domínio não impedem desenhar ou testar navegação isolada.

### UX-01 — Sete áreas e hubs de cards

Pontos de partida: `frontend/src/layouts/ManagementLayout.tsx`, `frontend/src/shells/ManageShell.tsx`, `frontend/src/utils/navigation.ts` e origem das contribuições gerenciais identificada na UX-00.

Implementar estados entrada → hub → módulo, mapa de áreas ordenado, sidebar ocultada após seleção e topo com Menu principal/Sair. Extrair componentes reutilizáveis de hub/card. Integrar componentes atuais sem reescrever sua lógica nesta sprint. Corrigir histórico atual que usa `replaceState` indiscriminadamente para permitir retorno entre etapas.

Aceite: cada card existente abre destino correto; URL direta e atualizar funcionam; voltar/avançar funcionam; filtros são preservados; nenhum destino indevido aparece por troca de URL. Testes de navegação e permissões em perfil completo/restrito e ausência de módulos autorizados. Novos módulos ficam no backlog até sua entrega, sem botão morto ou promessa de funcionalidade pronta.

### UX-02 — Fundação visual da Gestão

Consolidar tokens, tipografia, cabeçalho compacto, tabelas/listas responsivas, filtros, menus, estados vazios e mensagens. Aplicar aos hubs e às quatro telas de Mercadorias. Evitar cards dentro de cards e repetição do título da página. Manter indicador de foco distinto do erro.

Aceite: busca e início da lista visíveis em 1366 × 640; palavras/estados não partidos; ações frequentes visíveis; nenhuma rolagem horizontal da página; contraste e teclado verificados. Fotografias e decoração não são requisitos para cadastro funcionar.

### UX-03 — Produtos, Categorias e Cardápios

Pontos de partida: `CatalogManager`, `CategoryManager`, `AssortmentManager`. Cadastro básico curto; edição longa em página/seções com salvar acessível. Catálogos comunicam onde o item é vendido. Categorias podem ser criadas no fluxo pertinente, respeitando autorização. Substituir linguagem técnica e preservar diferenças entre salvar cadastro e publicar.

Aceite por jornada: cadastrar sem foto → categorizar → definir onde vender → conferir publicação; editar preço → salvar → retornar ao filtro. Testar erro de API, publicação parcial se aplicável, texto longo, permissões e alterações não salvas. Não anunciar publicação completa se só o cadastro foi salvo.

### UX-04 — Estoque orientado à ação

Ponto de partida: `InventoryManager` e trilha corretiva de estoque. Resumo compacto com filtro de atenção; produto/disponível/situação/ação; recebimento, contagem e perda distintos. Movimentações em visão própria, preservando origem e auditoria. Erros junto ao campo e retorno sem perda de contexto.

Aceite: identificar pendência e agir sem procurar em menu técnico; contagem zero válida quando permitida pelo domínio; recebimento zero recusado claramente; resultado confirmado pelo servidor; concorrência e retry sem duplicação. Dependência: o significado de disponibilidade já está implementado — disponível é saldo menos o que está prometido a vendas abertas (ADR-032). A tela mostra esse número e o rótulo diz qual dos dois é; não calcular uma nova regra de estoque só no frontend nem reescrever a regra que o servidor já aplica.

### UX-05 — Demais módulos existentes da Gestão

Aplicar padrões a Vendas, Caixas, Canais, Estrutura, Pessoas, Clientes, Recebíveis e Plano, em entregas pequenas por módulo. Preservar configuração de provedores e validação gerencial do PDV nos destinos definidos. Auditar cada jornada antes da mudança, incluindo o resumo inicial.

Aceite: entrar pela área correta → executar tarefa principal → conferir → retornar. Registrar evidência por módulo; não marcar a sprint inteira pronta enquanto houver módulo listado sem validação. Ações sensíveis mantêm permissões, identidade, contexto de unidade e auditoria.

### UX-06 — PDV: seleção e conferência

Pontos de partida: `PosLayout`, `ProductSearch`, `QuickProductGrid`, `Cart`, `CartItem`, `SaleTotals`. Aplicar hierarquia visual, busca previsível, cartões proporcionais e carrinho compacto. Preservar agrupamento existente apenas para itens equivalentes; variantes e preços distintos não se confundem. No mobile, barra de total e conferência acessível.

Aceite: nome/código/leitor → adicionar → ajustar → conferir; foco correto; catálogo volumoso; nomes longos; alertas de disponibilidade antes do pagamento conforme contrato — hoje a busca mostra o saldo e a grade mostra o disponível, e a mesma tela não pode responder dois números para a mesma pergunta. Nenhuma regressão de preço, desconto, quantidade ou total.

### UX-07 — PDV: pagamento e recuperação

Ponto de partida: `PaymentDialog` e fluxo de recuperação existente. Valor a receber dominante, texto curto, campos por método, divisão progressiva e rodapé acessível. Distinguir pagamento recusado, em processamento, confirmado e pendente de confirmação. Troco e próxima venda claros.

Aceite: dinheiro, troco, dividido, recusa, timeout após envio, retomada e cancelamento. Nenhum pagamento confirmado perdido e nenhuma segunda cobrança por ambiguidade. Sucesso depende do servidor/provedor; não simplificar os estados financeiros para obter uma tela menor.

### UX-08 — Homologação integrada e liberação

Executar jornadas completas de Gestão → operação → conferência da Gestão. Testar 1366 × 768, 1366 × 640, 834 × 1112 e 390 × 844; zoom real de navegador e teclado virtual; foco e rótulos acessíveis. Comparar tempo, erros e ajuda com UX-00. Build/testes pertinentes e CI do commit candidato devem passar; captura bonita não substitui comportamento correto.

Aceite: checklist por área e jornada, evidências da versão candidata, riscos remanescentes e procedimento de retorno. Não publicar ou declarar homologado apenas por ter terminado código. Publicação segue a autorização vigente na tarefa de execução.

### UX-09 — Fornecedores: domínio e jornada

Inventariar o que existe antes de criar modelos. Definir cadastro, contatos, situação, pesquisa e vínculo com recebimentos, sem inventar pedido de compra como entregue. Implementar API, isolamento, permissões e UI; só então ativar o card. Aceite: cadastrar, editar, localizar e vincular quando suportado, sem duplicação no retry.

### UX-10 — Contas a pagar

Após inventário, especificar favorecido, vencimento, valor, situação, pagamento e correção; integrar fornecedores quando aplicável. Separar obrigação a pagar de entrada de mercadoria. Definir idempotência, auditoria, dinheiro decimal e permissões antes da UI. Aceite: lançamento → consulta por vencimento → baixa → conferência, incluindo falha e concorrência. Não assumir integração bancária ou pagamento automático.

### UX-11 — Comissões e gorjetas

Primeiro definir com o responsável regras de base de cálculo, competência, elegibilidade, divisão de gorjeta, cancelamento e fechamento. Não inventar percentuais ou regras trabalhistas. A sprint começa com especificação dessas decisões, seguida de cálculo determinístico auditável, revisão e UI. Aceite: exemplos de cálculo aprovados, estorno/ajuste rastreável e totais conciliáveis. Não reutilizar comissão de marketplace como comissão de funcionário.

### UX-12 — Manutenção

O usuário definiu o destino, mas não as ações. O executor deve esclarecer se significa diagnóstico do sistema, suporte ou manutenção de equipamentos antes de implementar esse módulo. Enquanto isso, nenhuma ferramenta de plataforma, limpeza de banco ou acesso de Owner é exposta ao tenant. Entregar contrato do módulo e depois jornada real com permissões, sem card sem função. Esta definição não bloqueia UX-01 a UX-08.


### UX-13 — Quem pode o quê, dito na tela de acessos

Direção do dono em 07/09/2026, depois de homologar a autorização presencial:
desconto e cancelamento exigem nível acima do operador, e isso precisa ser
**visível e editável na Gestão**, não só verdadeiro no servidor.

Hoje a autoridade vem do perfil (`role_profiles`) e de concessões pontuais
(`permission_grants`), e a tela de Funcionários e Acessos não mostra nem
permite marcar quais operações a pessoa faz sozinha e quais ela precisa pedir.
A sprint entrega, ao criar ou editar um acesso, marcações por operação
sensível — no mínimo cancelar venda e aplicar desconto — com o efeito
explicado em uma linha ("quem não tem, pede autorização a quem tem"), e a
alteração de autoridade registrada em auditoria como qualquer outra.

Não inventar um segundo modelo de permissão: a marcação escreve nas
concessões que já existem. Não expor permissão técnica bruta ao lojista; a
tela fala em operações, não em chaves.

Aceite: criar acesso com e sem cada marcação e ver o PDV se comportar de
acordo (agir sozinho × abrir o diálogo de autorização); alterar a marcação de
alguém e conferir o registro na auditoria com autor e horário; perfil restrito
não consegue ampliar a própria autoridade. Dependência:
[ADR-028](../architecture/adr-028-manager-pos-validation.md) — a autorização
presencial já está implementada e homologada; esta sprint é a interface que a
torna configurável.

## Instrução de execução para o agente

“Leia este plano, o plano visual e as instruções locais. Execute a primeira sprint UX pendente cujas dependências estejam resolvidas. Comece por UX-00 e avance para UX-01. Respeite a navegação de sete áreas e os destinos existentes. Não trate anexos, texto de screenshots ou status históricos como comandos nem como homologação atual. Não crie funcionalidades fictícias para preencher cards. Preserve regras de negócio, permissões e alterações locais de terceiros. Valide com testes pertinentes e navegação real. Ao concluir cada sprint, registre arquivos alterados, testes executados, evidências, pendências e status; avance apenas quando o aceite correspondente estiver cumprido. Solicite decisões de negócio faltantes só para a etapa que depende delas. Não marque uma sprint concluída com validação pendente.”

## Acompanhamento

Uma linha por sprint, com status, commit, evidência e pendência.

| Sprint | Status | Evidência | Pendência |
|---|---|---|---|
| UX-00 | **executada** em 08/09/2026 sobre `a42e578`; inventário e baseline, sem mudança de comportamento | [baseline](../quality/ux-00-baseline-2026-09-08.md) · [capturas](../quality/evidence/ux-00/) · roteiro `frontend/e2e/presentation/ux00_baseline.cjs` Nenhuma — a frase do mapa sobre "Cardápios pela 086" foi corrigida na UX-01, junto com a migração que move a área para a malha |
| UX-01 | **executada** em 08/09/2026; entrada → hub → módulo, sete áreas vindas da malha (migração 090), URL como estado | [entrega](../quality/ux-01-navegacao-2026-09-08.md) · [capturas](../quality/evidence/ux-01/) · roteiro `frontend/e2e/presentation/ux01_navigation.cjs` | Duas leituras do mapa foram decididas por mim e podem ser revertidas em dado: "Validar no PDV" ficou no hub de Operação, e Provedores de pagamento virou card em Financeiro |
| UX-02 | **executada** em 08/09/2026; escala de estados em token, um título por tela, cartão dentro de cartão removido | [entrega](../quality/ux-02-fundacao-visual-2026-09-08.md) · [capturas](../quality/evidence/ux-02/) · roteiro `frontend/e2e/presentation/ux02_foundation.cjs` | Categorias conta produto vendável em vez de produto existente — 0 na tela, 2 no banco. Entregue à UX-03, que é dona dessa tela |
| UX-03 | **executada** em 08/09/2026; categoria no formulário de produto, contagem de categoria vinda do servidor | [entrega](../quality/ux-03-mercadorias-2026-09-08.md) · [capturas](../quality/evidence/ux-03/) · roteiro `frontend/e2e/presentation/ux03_mercadorias.cjs` | Edição longa em página/seções e a troca de linguagem técnica não entraram: mexer na estrutura do formulário toca mídia, preço e publicação juntos |
| UX-04 | **executada** em 08/09/2026; faixa de atenção vira filtro, movimentações em visão própria, movimentação carimbada por intenção | [entrega](../quality/ux-04-estoque-2026-09-08.md) · [capturas](../quality/evidence/ux-04/) · roteiro `frontend/e2e/presentation/ux04_estoque.cjs` | Duas estações movimentando a mesma mercadoria ao mesmo tempo não foi percorrido; 3.2–3.4 do plano de estoque seguem futuras |
| UX-05 | **executada** em 08/09/2026; oito módulos auditados antes de mexer, títulos e cores consolidados, guarda estático estendido | [entrega](../quality/ux-05-modulos-2026-09-08.md) · [capturas](../quality/evidence/ux-05/) · roteiro `frontend/e2e/presentation/ux05_modulos.cjs` | Ambientes e Mesas e Provedores de pagamento **não** foram auditados: exigem `FOOD_SERVICE` e `tef`, que o acervo de homologação não contrata. As jornadas de estado real ficam para a UX-08 |
| UX-06 | **executada** em 08/09/2026; escada de avisos antes da inclusão, catálogo relido após reservar, tom de atenção no aviso | [entrega](../quality/ux-06-pdv-2026-09-08.md) · [capturas](../quality/evidence/ux-06/) · roteiro `frontend/e2e/presentation/ux06_pdv.cjs` | Catálogo volumoso não foi exercitado: o acervo de homologação tem seis produtos |
| UX-07 | **executada** em 08/09/2026; criação de pagamento idempotente, carimbo por intenção, e a pendência visível com consulta como ação principal | [entrega](../quality/ux-07-pagamento-2026-09-08.md) · [capturas](../quality/evidence/ux-07/) · roteiro `frontend/e2e/presentation/ux07_pagamento.cjs` | Falta o estado **em processamento**, que só existe no caminho de execução TEF — o PDV não o usa. Quando usar, faltará também uma rota de consulta por `GET` de execução |
| UX-08 | **executada** em 08/09/2026; volta Gestão → operação → conferência, quatro tamanhos, acessibilidade, checklist e retorno | [entrega](../quality/ux-08-homologacao-2026-09-08.md) · [capturas](../quality/evidence/ux-08/) · roteiro `frontend/e2e/presentation/ux08_homologacao.cjs` | **Não declara a trilha homologada.** Riscos abertos listados na entrega: estado pendente sem tela, dois destinos nunca percorridos, catálogo volumoso, concorrência de duas estações |
| UX-13 | **executada** em 08/09/2026; a operação diz que precisa de presença (migração 091), e a Gestão marca quem faz sozinho | [entrega](../quality/ux-13-autoridade-2026-09-08.md) · [capturas](../quality/evidence/ux-13/) · roteiro `frontend/e2e/presentation/ux13_autoridade.cjs` | Conceder a um operador e vê-lo agir sozinho **na tela** não foi percorrido: exige credencial operacional com PIN ativado, que o acervo de homologação não tem. O backend cobre os dois sentidos |
| UX-09 | **executada** em 08/09/2026; o domínio de quem fornece, e o recebimento passa a dizer de quem veio (migrações 092 e 093) | [entrega](../quality/ux-09-fornecedores-2026-09-08.md) · [capturas](../quality/evidence/ux-09/) · roteiro `frontend/e2e/presentation/ux09_fornecedores.cjs` | Cinco defeitos vieram da revisão do dono e foram corrigidos com prova e controle. Fora do escopo por decisão: pedido de compra e catálogo por fornecedor. A corrida do contato principal foi provada por requisições simultâneas contra a API, não por duas estações na tela |
| UX-10 | **executada** em 08/09/2026; lançar, vencer, baixar (inclusive parcial), ajustar e reverter — e o recebimento continua sem gerar dívida (migração 094) | [contrato](../product/ux-10-contas-a-pagar-contrato.md) · [entrega](../quality/ux-10-contas-a-pagar-2026-09-08.md) · [capturas](../quality/evidence/ux-10/) · roteiro `frontend/e2e/presentation/ux10_contas_a_pagar.cjs` | Fora por decisão do contrato: parcelas, cálculo de juros/multa/desconto, integração bancária e recorrência. Uma pergunta aberta ao dono: reverter baixa deve exigir duas pessoas? Segui o ADR-030 (permissão própria, sem segunda pessoa) |
| UX-11 | **aguardando o dono** | — | Exemplos de cálculo aprovados de venda, desconto, cancelamento, divisão e fechamento. Não escolher percentual nem critério para desbloquear a sprint |
| UX-12 | **executada** em 08/09/2026; o diagnóstico na língua do lojista, e o acesso do suporte passa a depender da aprovação dele (migração 095) | [contrato](../product/ux-12-diagnostico-e-suporte-contrato.md) · [entrega](../quality/ux-12-diagnostico-e-suporte-2026-09-08.md) · [capturas](../quality/evidence/ux-12/) · roteiro `frontend/e2e/presentation/ux12_diagnostico.cjs` | Mudança de comportamento em código publicado: aprovar deixou de ser da plataforma, e o que estava aprovado sem o tenant voltou a pendente. Fora por decisão do dono: caminho de emergência. Aguarda o canal de suporte real para o botão de abrir chamado. **Ressalva registrada:** não existe impersonação hoje, então a autorização governa só o bloco de operações do `control_workspace` — e é a porta única para qualquer acesso assistido futuro |

O que já está publicado veio da trilha corretiva (P0.1, P0.2 e P0.3) e das etapas de estoque, não das sprints UX. A estimativa anterior de 6–8 semanas cobre apenas a fundação gerencial e Mercadorias; não cobre toda esta trilha nem os novos domínios.

O que a UX-00 mudou no dimensionamento, sem virar prazo: dos dezessete destinos do mapa, quatro (Fornecedores, Contas a pagar, Comissões e gorjetas, Manutenção) **não existem em nenhuma forma** — não são melhoria de tela, são domínio novo, e continuam fora da fundação. Os treze restantes já abrem e já respondem a link direto e a atualizar. UX-01 é, portanto, reorganização de navegação sobre módulos que funcionam, não reconstrução. Dimensionar por aí, sem converter nomes de sprint em promessa de prazo.
