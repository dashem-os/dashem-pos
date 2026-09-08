# Plano de evolução da experiência DASHEM

Data: 07/09/2026. Status: proposta de produto e execução, sem implementação ou homologação por este documento.

Objetivo: tornar a operação compreensível à primeira vista, rápida sob pressão e visualmente consistente. A beleza deve resultar de hierarquia, legibilidade, composição e comportamento previsível.

Prioridade revisada após o retorno do usuário: **Gestão primeiro**, começando pela navegação compartilhada, Produtos, Estoque, Catálogos e Categorias. O PDV permanece no escopo, após esse primeiro conjunto. A experiência gerencial é parte central do produto.

Execução detalhada: [sprints UX-00 a UX-12 — Gestão e PDV](ui-ux-implementation-sprints.md). Essa trilha incorpora a decisão posterior do usuário de sete áreas com hubs de cards e prevalece sobre a estimativa e o agrupamento preliminares deste documento.

## Evidências e limites

Referências de arquitetura: [ADR-034 — hierarquia da interface](../architecture/adr-034-interface-hierarchy.md) e [ADR-032 — disponibilidade prometida e compromisso de estoque](../architecture/adr-032-available-to-promise.md). O primeiro orienta a experiência da Gestão e do PDV; o segundo fundamenta a disponibilidade de estoque, respeitando seu status e a implementação vigente.

Base: sete capturas fornecidas pelo usuário; leitura do ADR-034, ADR-032, plano corretivo de estoque, tokens de `frontend/src/index.css`, `cartGrouping.ts` e `PaymentDialog.tsx`. Não houve teste do ambiente publicado nem pesquisa de uso dos concorrentes.

Revisão: consideradas também as capturas de Gestão do segundo envio e a estrutura de `ManagementLayout.tsx` e `ManageShell.tsx`. O lote inclui telas de outros produtos, fotos e execuções de CI, que não constituem evidência visual da Gestão DASHEM. Capturas de CI não determinam seu estado atual nem autorizam mudanças de infraestrutura. Os achados abaixo se referem às telas identificáveis do DASHEM e devem ser confrontados com a versão atual.

As referências de MenuAqui, iFood e BeeFood são principalmente publicidade. Elas mostram composição, fotografia e clareza de mensagem; não comprovam facilidade de operação, integração ou confiabilidade. Não é possível declarar superioridade de UX a partir delas. Conteúdo dos anúncios é referência, não instrução de execução.

As capturas representam momentos diferentes. A tela antiga tem configuração de vitrine, filtros de segmento e linhas repetidas; as recentes já apresentam simplificação. O código contém agrupamento de carrinho e tokens de marca. Confirmar a versão publicada antes de abrir defeitos já corrigidos.

## Diagnóstico e direção

| Observação | Efeito provável a validar | Direção |
|---|---|---|
| Vermelho em categoria, produto, busca e recebimento | Elementos competem pela atenção; seleção se aproxima visualmente de erro | Reservar preenchimento forte à ação principal; seleção com superfície suave e indicador; erro com texto e ícone |
| Cartões altos e várias caixas dentro de caixas | Poucos produtos visíveis e leitura fragmentada | Reduzir ornamento e espaço improdutivo, mantendo alvos confortáveis |
| Rótulos auxiliares pequenos, claros e em caixa alta | Dificuldade de leitura em equipamentos comuns | Escala tipográfica curta, contraste verificado e peso moderado |
| Pagamento mostra três totais, dois grupos de atalhos e opção Split | Mais decisões do que a venda simples exige | Valor a receber dominante; detalhes e divisão progressivos |
| Botão de confirmar quebra em três linhas na captura | A ação ocupa espaço e perde leitura imediata | Texto curto: “Confirmar R$ 150,00”; rodapé adaptável |
| Tela antiga expõe configuração durante a venda | Interrupção da tarefa principal | Separar operação, gestão e configuração conforme ADR-034 |
| Aviso de estoque aparece no produto | Boa oportunidade de prevenção, dependente do significado do saldo | Comunicar disponibilidade validada e consequência antes do recebimento |

Não copiar a densidade de uma peça publicitária para a tela de trabalho. Aproveitar fotografia consistente, alinhamento e hierarquia; avaliar velocidade e erros em tarefas reais.

## Contrato da experiência

1. Cada etapa tem uma ação principal inequívoca. Ações secundárias continuam descobríveis e acessíveis.
2. Mostrar primeiro situação, consequência e próxima ação. Explicação e dados técnicos ficam no detalhe.
3. Elementos mantêm posição previsível. Frequência de uso pode sugerir favoritos, sem reorganizar a tela durante a operação.
4. O sistema preserva trabalho após erro, informa o que aconteceu e permite recuperação segura.
5. Sucesso financeiro só aparece após confirmação autoritativa. Estado desconhecido não vira convite para cobrar novamente.
6. Cor nunca é a única indicação de seleção, risco ou sucesso.
7. Personalização respeita função e contexto: operador, gerente e cliente final compartilham identidade, mas têm jornadas próprias.

## Gestão: diagnóstico e jornada prioritária

O gestor deve conseguir **identificar uma pendência → entender o impacto → agir → conferir o resultado**. Hoje a composição privilegia títulos, explicações e contêineres, enquanto a informação de trabalho chega tarde na página.

| Evidência nas capturas | Problema | Entrega e aceite |
|---|---|---|
| Categorias 193218 e Estoque 205841: grandes painéis de título e descrição | A introdução ocupa espaço desproporcional à tarefa | Cabeçalho compacto com título, unidade e ação; busca e início da lista visíveis em 1366 × 640 |
| Produtos 193340: menu, aba, cadastro e “Validar no PDV” em vermelho forte | Navegação e saída para outra superfície competem com a ação local | Seleção lateral discreta; ação principal local dominante; acesso ao PDV secundário e corretamente identificado |
| Menu lateral largo, espaçado e com rolagem própria | Localização dos módulos exige exploração | Navegação compacta e estável, grupos por tarefa; acesso às áreas essenciais testado em tela baixa |
| Produtos 193522: instruções de publicação e ajuda antes da lista | Trabalho diário recebe explicação repetida | Ajuda sob demanda e orientação contextual somente quando necessária |
| Produto 193446 e catálogo 193258: formulários extensos dentro de diálogo | Perda de contexto e ação final parcialmente visível ou ausente na captura | Edição extensa em página dedicada com seções e barra de salvar; diálogo apenas para ação curta; validar rolagem e foco |
| Catálogo 193258: “Versão esperada”, “Contextos operacionais habilitados” | Vocabulário interno exige tradução mental | “Onde vender”, nomes de canais e detalhes técnicos fora do fluxo comum |
| Estoque 205841: ações frequentes dentro de reticências | Limpeza aparente pode esconder o caminho de trabalho | “Receber mercadoria” visível na lista ou barra; ações menos frequentes em menu contextual identificado |
| Estoque 193159: histórico extenso abaixo dos saldos | Mistura conferência atual e investigação histórica | Abas “Disponibilidade” e “Movimentações”, com filtros; manter rastreabilidade de cada evento |
| Recebimento 180633: erro repetido no formulário e toast | Mensagem técnica e duplicada desvia atenção | Erro junto ao campo: “Informe uma quantidade maior que zero”; preservar o preenchimento |
| Capturas antigas 145225 e 145156: palavras partidas | Colunas e etiquetas sem espaço mínimo | Revalidar a correção existente; nomes, códigos e estados legíveis em todos os tamanhos |

As capturas mostram evolução: o resumo de estoque já passou de cartões numéricos a “2 produtos precisam de atenção”. Isso melhora a mensagem, mas o painel ainda ocupa muita altura. Concluir o trabalho requer ajustar composição e interação, além de texto.

### Estrutura proposta para toda a Gestão

Na entrada, sidebar com sete áreas. Ao escolher uma área, a sidebar desaparece e o conteúdo apresenta cards das funcionalidades. No topo global, somente as ações “Menu principal” e “Sair”, com contexto textual discreto. O módulo aberto pelo card oferece retorno à sua área dentro do conteúdo. Cabeçalho único por página, resumo acionável quando útil, busca/filtros e área de trabalho seguem um padrão comum.

Mapa definido pelo usuário, nesta ordem: **Operação; Mercadorias; Estrutura; Pessoas; Relacionamento; Financeiro; Administração**. Os cards e destinos estão na trilha de sprints. Preservar permissões e disponibilidade de módulos: `ManagementLayout` monta a navegação por contribuições, então reorganizar visualmente exige reconciliar os rótulos e grupos dessa origem, sem inserir acessos indevidos.

### Entregas por área

- **Início:** prioridades com ação direta, período e unidade explícitos. Indicadores apenas quando ajudam uma decisão. Não mostrar zero como substituto de dado indisponível. Validar esta proposta na tela real, ainda não auditada neste envio.
- **Produtos:** lista com nome, preço, disponibilidade relevante e onde está à venda; edição acessível. Busca, filtros e retorno preservam posição. Cadastro básico com nome, preço e campos realmente obrigatórios; foto e opções avançadas não bloqueiam sem necessidade de domínio.
- **Estoque:** resumo compacto que filtra os itens em atenção. Lista com produto, disponível, situação e ação contextual. Receber, contar e registrar perda têm fluxos distintos, unidade explícita e efeito explicado antes de confirmar. “Repor” não registra uma entrada fictícia: só receber mercadoria efetivamente chegada altera saldo por entrada.
- **Catálogos e cardápios:** nome, canais/unidades, itens e situação; “Gerenciar produtos” como ação clara. Escolher onde vender usando nomes concretos, com resumo do alcance antes de publicar. Distinguir edição do cadastro e alteração de publicação sem exigir que o usuário estude essa arquitetura.
- **Categorias:** lista simples e criação curta, inclusive a partir do cadastro de produto quando autorizado. Estado vazio oferece “Criar categoria”; busca sem resultado oferece limpar filtro. Não sugerir que categorias são obrigatórias se o domínio permite vender sem elas.
- **Vendas, caixas e financeiro:** próxima onda própria, com conferência, pendências e detalhe rastreável; auditar telas antes de especificar mudanças. Mesma fundação visual desde o início.
- **Clientes, equipe e configurações:** aplicar navegação e padrões comuns; aprofundar as jornadas por frequência e impacto, sem alegar diagnóstico de telas não examinadas.

### Modelo de Estoque a prototipar

Cabeçalho: “Estoque · Matriz” e “Receber mercadoria”. Faixa: “2 produtos precisam de atenção” com “Ver produtos”. Barra: busca e filtros. Lista: produto, disponível, situação e ação. “Movimentações” abre uma visão específica com produto, período, tipo e origem.

Ao receber Coca-Cola, mostrar produto/unidade, quantidade recebida e saldo previsto, quando calculável com dados atuais. Ao contar, solicitar quantidade encontrada e mostrar diferença. Ao salvar, confirmar resultado do servidor e atualizar lista sem perder busca. Conflito concorrente preserva o trabalho e pede nova conferência, sem anunciar sucesso.

## PDV: jornada posterior de encontrar → adicionar → conferir → receber

**PDV em computador:** busca e categorias à esquerda; catálogo no centro da área de seleção; venda à direita com itens compactos, quantidade, valor e total fixo. Cabeçalho operacional discreto. Avisos relevantes permanecem acessíveis, inclusive indicação de acesso gerencial, sem disputar o centro da operação.

**PDV em tablet ou celular:** catálogo ocupa a largura disponível; barra inferior mostra quantidade, total e “Receber”. “Ver itens” abre a conferência. Teclado virtual e áreas seguras não podem esconder o campo ativo ou a ação final. Adaptar a composição à largura e altura efetivas, sem simplesmente encolher a tela desktop.

**Produtos:** nome e preço prioritários; fotos com proporção e tratamento consistentes; fallback digno para ausência de foto. Código fica secundário e pesquisável. Produto com variantes ou complementos abre seleção antes de adicionar. Agrupar apenas itens operacionalmente equivalentes; preservar diferenças de preço, personalização e descontos que importem à conferência.

**Busca:** nome e código, leitor e teclado. Exibir resultado inequívoco, vazio útil e erro recuperável. Após inclusão simples, devolver foco à busca quando apropriado. Atalhos devem ser visíveis sob demanda e não causar confirmação financeira acidental.

**Pagamento simples:** título “Receber R$ 150,00”; escolher meio; mostrar somente campos pertinentes. Em dinheiro, “Valor entregue” e “Troco”, com poucos atalhos úteis. “Usar mais de uma forma” revela divisão; “Já pago” e saldo ganham destaque quando houver pagamento parcial. Traduzir métodos internos na lista de recebimentos.

**Pagamento com falha:** distinguir processando, confirmado, recusado e confirmação pendente. Preservar pagamentos confirmados. Oferecer consulta de status quando houver incerteza e impedir duplicação. Conclusão mostra resultado, troco quando aplicável e “Nova venda”.

## Direção visual

Evoluir os tokens existentes, preservando a identidade DASHEM. Fundo neutro, superfícies claras, texto escuro e vermelho usado com intenção. Consolidar estados de marca, seleção, foco, sucesso, atenção e erro, incluindo variantes por segmento já existentes.

Definir uma família tipográfica de interface, poucos pesos e uma escala curta. Priorizar números monetários legíveis, alinhamentos consistentes e nomes sem cortes ambíguos. Padronizar espaçamento em múltiplos de 4, dois ou três raios de borda e sombras discretas apenas onde indiquem sobreposição.

Criar componentes de referência para botão, campo, busca, cartão de produto, linha de venda, resumo, mensagem contextual, diálogo e confirmação. Documentar estados vazio, carregando, erro, desabilitado, foco e texto longo. Não trocar biblioteca ou framework sem necessidade demonstrada.

## Inteligência que reduz trabalho

| Capacidade | Benefício | Dependência e limite |
|---|---|---|
| Disponibilidade antes da inclusão | Evitar descobrir falta durante pagamento | Entregue no servidor em 07/09/2026: reserva na inclusão, disponível e recusa antes do pagamento, com concorrência serializada. Falta na tela o aviso antes da recusa, e falta a homologação em duas estações |
| Favoritos sugeridos por contexto | Encontrar itens frequentes rapidamente | Histórico suficiente e controle do operador; posição estável |
| Reposição orientada | Mostrar quais produtos exigem ação e por quê | Dados confiáveis; distinguir regra manual de previsão |
| Recuperação de pagamento | Evitar cobrança duplicada e perda de contexto | Estado autoritativo do provedor, idempotência e fluxo existente de recuperação |
| Preenchimento assistido | Reduzir digitação e repetição | Padrões explícitos e reversíveis; valores financeiros continuam visíveis |

Priorizar regras determinísticas, bons padrões e prevenção. IA generativa pode explicar ou auxiliar cadastro em uma fase posterior; não é pré-requisito nem autoridade para saldo, preço, permissão ou confirmação financeira.

## Execução por entregas

Estimativa inicial revisada: 6–8 semanas para a fundação da Gestão e as quatro superfícies de mercadorias, assumindo uma pessoa de design/produto e uma de frontend, com apoio de backend e usuários para validação. Reestimar após diagnóstico; não é compromisso de prazo. PDV e aprofundamento dos demais módulos precisam de estimativa própria; não estão incluídos nesse prazo.

| Etapa | Entrega concreta | Critério de saída |
|---|---|---|
| 1 — diagnóstico, 3–5 dias | Inventário da versão publicada, mapa de tarefas, baseline de tempo/erros e backlog por gravidade | Problemas reproduzidos e separados entre visual, interação e domínio |
| 2 — desenho, 1 semana | Protótipo da navegação gerencial, Produtos, Estoque e edição, desktop e tela estreita | Gestores encontram produto, identificam pendência e concluem correção sem orientação recorrente |
| 3 — fundação da Gestão, 1–2 semanas | Tokens, navegação, cabeçalho, listas, filtros e formulários; Produtos e Estoque | Conteúdo útil visível, ações encontráveis, salvar acessível e dados preservados |
| 4 — jornada de mercadorias, 1–2 semanas | Catálogos, Categorias e fluxo integrado cadastrar → organizar → disponibilizar → conferir | Usuário conclui a jornada sem aprender termos internos; escopo de publicação claro |
| 5 — piloto, 1 semana | Uso controlado, correção dos principais atritos e comparação com baseline | Metas de usabilidade atingidas e nenhuma regressão crítica |
| 6 — ondas seguintes, a estimar | Vendas/caixas/financeiro; PDV/pagamento; clientes/equipe/configurações; mesas/cozinha e cardápio | Cada jornada passa pelo mesmo protocolo, priorizada por frequência e impacto |

Produto/design responde pela hierarquia e pesquisa; frontend pelos componentes e interação; backend pelos contratos e integridade; QA e operadores validam as jornadas. Uma mesma pessoa pode acumular papéis, com ajuste da estimativa.

Antes da etapa 2, reconciliar este backlog com ADR-034 e a trilha corretiva de estoque. Não duplicar iniciativas nem atribuir entrega a uma decisão documental. Implementação incremental por jornada, com retorno à versão anterior planejado e sem alteração de dados de negócio para fins estéticos.

## Validação e metas propostas

Medir baseline antes de fixar metas finais. Testar inicialmente com 5–8 pessoas, incluindo gestores e responsáveis por cadastro/estoque, novos e experientes; incluir caixas na etapa do PDV. A amostra é exploratória e não prova superioridade de mercado.

- Pelo menos 90% das tarefas essenciais concluídas sem ajuda na rodada de validação; registrar também números absolutos e resultados por tarefa.
- Reduzir em pelo menos 25% a mediana de tempo para encontrar/editar produto e registrar recebimento comparáveis, sem aumentar erros. Aplicar a mesma comparação à venda na etapa do PDV; separar espera de rede.
- Ao menos 4 de 5 participantes identificam a próxima ação em até 5 segundos nos estados principais.
- Nenhum defeito crítico observado de cobrança duplicada, total incorreto, perda de venda ou bloqueio de ação final; complementar observação com testes de integração.
- Verificar navegação por teclado, foco visível, rótulos acessíveis, contraste, zoom de 200% e leitor de tela no fluxo principal. Alvos de toque de pelo menos 44 × 44 CSS px como meta de projeto.
- Validar 1366 × 768, 1366 × 640, tablet 834 × 1112 e celular 390 × 844, ajustando à frota real. Sem rolagem horizontal da página ou ações encobertas.

Cenários obrigatórios da Gestão: localizar produto; alterar preço; cadastrar sem foto; criar categoria; escolher onde vender; identificar item em atenção; receber mercadoria; contar incluindo zero; registrar perda; consultar movimentação; voltar mantendo filtro; erro de campo; conflito concorrente; falha de rede; usuário sem permissão; nomes longos; listas vazias e volumosas; teclado virtual. Salvar não pode ficar encoberto e falhas não podem descartar dados ou duplicar movimentos.

Cenários da etapa posterior do PDV: venda por código; busca por nome; quantidade e remoção; item com complemento; indisponibilidade; dinheiro com troco; pagamento dividido; recusa; timeout após envio; retomada sem duplicação; nome longo; catálogo sem imagens; catálogo volumoso; teclado virtual.

Registrar tempo, erros, pedidos de ajuda, cliques de retorno e comentários. Usar dados de teste ou evidências sem informações pessoais. Capturas verificam composição; jornadas e testes verificam comportamento. A beleza deve ser avaliada junto da clareza percebida, sem substituir desempenho operacional.

## Primeiro recorte recomendado

Começar pela **Gestão: navegação + Produtos + Estoque + edição de produto + recebimento de mercadoria**, com erro e sucesso. O primeiro protótipo deve permitir encontrar um produto, editar seu preço, identificar falta e registrar uma entrada, em desktop e tela estreita. Em seguida, completar Catálogos e Categorias. A referência visual nasce dessas telas de trabalho e se estende ao PDV e demais módulos.
