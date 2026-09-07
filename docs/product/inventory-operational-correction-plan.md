# Aditivo à trilha corretiva da Gestão — Estoque e almoxarifado

Status: **plano proposto para execução; nenhuma etapa homologada por este documento**.
Data: 06/09/2026. Origem: homologação visual do dono do DASHEM POS e revisão do código.

## Resultado que o cliente precisa obter

O cliente deve conseguir cadastrar mercadoria, receber reposição, vender, registrar
perda e conferir o saldo sem estudar a arquitetura do sistema. Ao ver “Repor”,
deve encontrar ali a ação adequada e saber o que acontecerá ao confirmar.

Este é um aditivo à [trilha corretiva da Gestão](tenant-management-correction-sprints.md),
com gates próprios de conclusão abaixo. Não renumera sprints existentes, não
declara ADR aceito e não reabre indiscriminadamente gates já concluídos. Reabre
a prontidão operacional de estoque e das superfícies de mercadorias afetadas.
O escopo inclui Produtos e preços, Estoque, Categorias e Sortimentos/cardápios.

Correção de saldo e usabilidade básica têm prioridade sobre novas funcionalidades
nessas superfícies. O estoque não deve ser apresentado como homologado enquanto
os gates de integridade, operação e apresentação estiverem pendentes.

## Evidências e limites do diagnóstico

As cinco capturas fornecidas nesta conversa mostram:

- Produtos e preços: tipo “PRODU / TO”, SKU partido e muitas ações concorrentes;
- Sortimentos: “ATIV / O”, títulos partidos e pouco espaço útil para a informação;
- Estoque: “Repor” separado de “Movimentar”, texto sobre “fatos persistidos” e
  indicador que soma unidades, sem explicar uma decisão ao lojista;
- Categoria: termo “Slug” exigido na operação comum. O seletor nativo aberto
  sobrepõe temporariamente o botão; a captura isolada não prova defeito de foco;
- Edição de sortimento: formulário longo, ação final fora da captura e versão
  técnica em destaque. Deve ser testado se a ação permanece alcançável.

O código revisado oferece estoque inicial, movimentos, saldos, mínimos e uma
tela de estoque. Isso comprova implementação parcial, não a conclusão da jornada.
Referências para o executor, relativas à raiz do repositório:

| Evidência no código | Consequência / trabalho exigido |
|---|---|
| `frontend/src/context/PosContext.tsx`: cadastro envia entrada inicial | Conferir saldo e histórico após criação; tratar falhas parciais sem duplicar produto |
| `CatalogManager.tsx` e `InventoryManager.tsx`: quantidade enviada sem regra de sinal | Perda positiva pode virar entrada; corrigir contrato no servidor |
| `backend/app/services/inventory_service.py`: soma quantidade recebida | Tipo de operação precisa determinar efeito autorizado |
| `inventory_service.adjust_stock` faz commit e é chamado no laço de itens de `payment_service` | Risco de confirmação parcial entre itens; exigir teste de falha no segundo item e corrigir fronteira transacional |
| `PosContext.adjustStock` captura erro sem propagá-lo | Chamador pode encerrar formulário ou anunciar sucesso após falha; tornar resultado inequívoco |
| `InventoryManager` lista `products` do contexto; contexto usa catálogo vendável | Investigar exclusão de itens não publicados, filtros de atividade e paginação; estoque deve consultar acervo próprio |

Não foram executados neste planejamento testes contra o ambiente publicado.
Não há aqui afirmação de que dados históricos estejam corrompidos: há um caminho
que permite gravá-los incorretamente e precisa de diagnóstico somente de leitura.

## Contrato operacional proposto

### Ações com significado único

| Ação vista pelo cliente | Informação solicitada | Efeito calculado pelo servidor |
|---|---|---|
| Receber mercadoria | Quantidade recebida, positiva, unidade e referência opcional | Acrescenta ao saldo |
| Registrar perda | Quantidade perdida, positiva, motivo obrigatório | Subtrai do saldo |
| Contar estoque | Quantidade encontrada, zero ou positiva | Calcula diferença para o saldo conferido |
| Receber devolução de cliente | Item, quantidade, venda quando aplicável e condição | Retorna ao saldo vendável somente se apto |
| Devolver ao fornecedor | Quantidade e motivo/referência | Retira do saldo de origem |
| Definir estoque mínimo | Quantidade mínima | Altera parâmetro, sem criar entrada/saída |
| Transferir mercadoria (etapa 3) | Origem, destino e quantidade | Movimentos vinculados, sem criar quantidade total |

O usuário não digita sinal negativo para representar uma perda. “Ajuste” não pode
significar simultaneamente diferença e saldo final. Ajuste técnico por diferença,
se mantido, fica em ação explícita e restrita; a ação cotidiana é “Contar estoque”.

O servidor valida tipo, unidade, precisão, quantidade finita, permissão e escopo
da loja. Rejeita payloads ambíguos, valores incompatíveis e operações manuais que
tentem se passar por baixa de venda. A versão da API e os chamadores existentes
devem ser inventariados antes da migração: não inverter indiscriminadamente os
sinais atuais nem corrigir somente o browser.

### Integridade obrigatória

1. Saldo anterior + variação assinada = saldo posterior em cada movimento.
2. O servidor deriva a variação da operação; conserva quantidade informada,
   unidade, ator autenticado, motivo, data e vínculo com a origem.
3. Movimento confirmado não é reescrito. Correção gera movimento compensatório
   vinculado, com justificativa e autorização.
4. Movimento, saldo, auditoria e idempotência confirmam juntos. Retry, duplo clique
   ou timeout não duplicam o efeito. Sucesso só aparece após confirmação.
5. Falha em um item da venda não pode deixar itens anteriores baixados e venda
   parcialmente confirmada. Revisar o commit interno do serviço de estoque;
   a transação composta pertence ao serviço que coordena a operação inteira.
6. Proposta conservadora inicial: não permitir saldo negativo vendável. Perda ou
   saída maior que o disponível é recusada com mensagem útil. Contagem concorrente
   verifica versão: se houve venda após a leitura, solicita nova conferência.
7. Nenhuma operação atravessa tenant, loja ou depósito autorizado. A interface
   não substitui a validação da API.
8. Valores decimais e conversões preservam precisão no banco e na API. Não usar
   `parseInt` para itens fracionados. Não somar kg, litros e unidades em um cartão.
9. Cancelamento antes da baixa não cria devolução fictícia. Estorno financeiro
   não devolve automaticamente mercadoria consumida, conforme o ADR-030.

### Venda, reserva e consumo: decisões explícitas

A implementação observada baixa produtos controlados na quitação da `Sale`.
Essa constatação não homologa mesa, pagamento parcial, crediário ou produção.
Antes de alterar esse momento, mapear cada caminho de fechamento e demonstrar
quando ele chama o estoque. Venda a prazo não pode permitir saída física sem
controle só porque o recebimento financeiro ocorre depois.

A etapa 1 preserva os contratos existentes enquanto corrige sinais, transações e
prova seus limites. Se um caminho ficar sem baixa adequada, registrar bloqueio
de homologação daquele caminho; não apresentá-lo como atendido.

Reservar durante pedido e consumir na produção são extensão da etapa 3. Exigem
decisão arquitetural específica, compatível com o [ADR-001](../architecture/adr-001-order-versus-sale.md),
que hoje não atribui movimento de estoque ao `OrderItem`. A extensão deve definir
reserva, liberação, consumo e evitar segunda baixa no pagamento.

## Desenho da experiência

### Página Estoque

Cabeçalho compacto: “Estoque” e loja selecionada. Ações visíveis: **Receber
mercadoria**, **Contar estoque** e **Histórico**. Indicadores acionáveis:
“Sem estoque”, “Abaixo do mínimo” e “Sem mínimo definido”, abrindo seus filtros.
Não ocupar a primeira tela com um bloco alto que empurre os produtos para baixo.

Lista: produto e código, saldo com unidade, mínimo, situação e ação principal.
Na linha com necessidade de reposição, mostrar **Receber mercadoria**. Separar
“preparar compra” de “receber”: alerta não significa que mercadoria já chegou.
Perda, devolução e detalhes ficam em menu secundário com rótulos claros.
Produto sem permissão de movimentação oferece consulta e explica quem pode agir;
não sugerir uma ação que termina em recusa sem orientação.

O acervo inclui produtos não publicados no PDV e materiais de uso interno.
Publicação, aba comercial ou disponibilidade para venda não governam a existência
física do estoque. Busca por nome, SKU e código de barras deve realmente cobrir
os campos anunciados e consultar todas as páginas. Falha de carregamento exibe
erro e “Tentar novamente”; não “Nenhuma movimentação” como se o histórico fosse vazio.

### Recebimento, perda e contagem

Um formulário por intenção, compartilhado entre Produtos e Estoque, evitando
duas implementações divergentes. Cabeçalho identifica produto, loja e unidade.
Mostrar saldo atual, campo principal, motivo/referência e prévia:

- “Você receberá 5 un. Saldo: 8 → 13 un.”
- “Você registrará perda de 1 un. Saldo: 13 → 12 un.”
- “Você contou 10 un. O sistema registra 12. Diferença: −2 un.”

A prévia não é autoridade: ao confirmar, o servidor valida concorrência. Botão
nomeia a ação (“Registrar recebimento”, “Registrar perda”, “Confirmar contagem”).
Erro mantém os dados preenchidos, não fecha o formulário e não exibe sucesso.
Configurar mínimo tem ação independente: não obrigar movimentação fictícia.

### Ficha de produto

Separar identificação/preço, estoque e publicação em áreas com propósito claro.
Na edição, apresentar saldo e acesso direto a **Receber mercadoria**, **Registrar
perda** e **Histórico**. Estoque inicial só pertence à criação e indica a loja.
Arquivar não apaga estoque nem histórico; saldo remanescente continua consultável.
Excluir não deve concorrer visualmente com a ação cotidiana principal.

### Categorias e publicação

Categoria comum pede nome e, opcionalmente, categoria superior. Gerar identificador
automaticamente; slug fica em detalhes avançados quando realmente necessário,
preservando a estabilidade dos identificadores existentes.

Publicação usa linguagem da atividade e explica onde o item aparecerá, sem expor
“versão esperada”, “tenant”, “ledger”, “fatos persistidos”, “slots” ou chaves internas.
Versão continua protegendo concorrência no backend. Campos de publicação não se
misturam com movimentação de estoque. Em conta mista, explicitar o contexto sem
trocar a atividade contratada ou esconder mercadoria de outra atividade.

### Regras de apresentação verificáveis

- Badges e rótulos curtos como “Produto”, “Ativo”, “Repor” e unidades não quebram
  no meio da palavra. Nome longo quebra entre palavras; código tem apresentação
  própria. Não resolver reduzindo fonte ou escondendo informação essencial.
- Tabelas distribuem largura por conteúdo e prioridade. Em espaço insuficiente,
  mudam para fichas com rótulos; não comprimem todas as colunas até ficarem ilegíveis.
- Um componente compartilhado governa modal, espaçamento, foco e área de ações.
  Cabeçalho e rodapé permanecem acessíveis; corpo tem rolagem própria. Formulário
  complexo pode usar página/painel amplo em vez de um modal estreito.
- Rodapé não cobre campos; último campo pode ser rolado totalmente acima dele.
  Seletores, mensagens de erro e teclado virtual não tornam salvar/cancelar inacessíveis.
- Testar seletor aberto e fechado: sobreposição transitória nativa não é, sozinha,
  defeito; perda de acesso, corte ou foco inacessível é.
- Alvos de toque de pelo menos 44 px, foco visível, navegação por teclado,
  rótulos associados e contraste suficiente. Ícones isolados só em ações secundárias
  com nome acessível e identificação compreensível.

## Estoque inteligente, sem prometer um almoxarifado que ainda não existe

### Núcleo comum aos nichos

Saldo, histórico, recebimento, perda, contagem, mínimo e reposição são comuns.
Produto físico, serviço e material consumido são comportamentos diferentes,
não apenas nomes diferentes na interface.

| Cenário | O que precisa ser provado |
|---|---|
| Varejo: lata, roupa, caixa de produtos | Unidade/SKU/variante corretos, venda, devolução e conversão de embalagem explícita |
| FOOD: bebida pronta | Recebimento e baixa da mercadoria efetivamente vendida |
| FOOD: hambúrguer preparado | Receita/ficha técnica, ingredientes, rendimento, perdas e momento de consumo; não fingir estoque de hambúrguer pronto |
| Beleza: revenda | Mesmo núcleo de mercadoria, lote/validade quando adotados |
| Beleza: serviço com material | Serviço não tem saldo físico; consumo de material exige vínculo próprio |
| Conta mista | Estoque físico não desaparece ao trocar contexto comercial; movimentos não se duplicam |

### Reposição assistida

Primeiro entregar regra explicável: mínimo e estoque-alvo configurados; mostrar
quantidade sugerida e a conta usada. Zero sem mínimo definido aparece como “Sem
estoque”; não inventar uma política de compra. Quando houver reservas, usar saldo
disponível; quando houver compras pendentes, mostrá-las separadamente e evitar
sugestão duplicada. Sem esses dados, assumir explicitamente que a sugestão usa
somente saldo físico e parâmetros manuais.

Depois, incorporar consumo histórico, prazo do fornecedor, embalagem e estoque
de segurança. Exibir período, base e insuficiência de dados. A recomendação é
editável; nunca gera compra ou entrada física automaticamente. IA não participa
da conta autoritativa nem do caminho crítico.

**Os algoritmos desta etapa ainda não estão especificados, e o parágrafo acima
não é especificação.** São dois trabalhos distintos, e o primeiro não entrega o
segundo:

| Trabalho | Pergunta que resolve |
|---|---|
| Integridade dos movimentos (etapa 1) | Recebi, vendi ou perdi: quanto ficou? |
| Planejamento de reposição (etapa 3) | Quando comprar e quanto comprar? |

O que a especificação precisa definir, com critério de aceite por item:

- **ponto de reposição** — demanda esperada durante o prazo de entrega mais o
  estoque de segurança;
- **estoque de segurança** — calculado sobre a variação da demanda, a variação do
  prazo de entrega e o nível de atendimento desejado, que é decisão comercial e
  precisa ser configurável;
- **lote econômico** — equilíbrio entre custo por pedido e custo de manter
  estoque. Sem custo de pedido e custo de carregamento no cadastro, ele não tem
  como funcionar, e a ausência desses dados precisa ser dita na tela em vez de
  suprida por constante;
- **previsão de demanda** — por produto e unidade, avaliada contra métodos
  simples como referência e com o erro medido e exibido. **Dias sem estoque
  precisam sair da base: venda zero não é demanda zero**, e tratá-la como zero
  ensina o sistema a comprar cada vez menos do que mais falta;
- **FOOD** — validade, rendimento da ficha técnica, ingredientes e desperdício. Um
  lote economicamente ótimo pode ser grande demais para ser consumido antes do
  vencimento, e nesse caso a recomendação econômica está errada.

A entrega é uma recomendação explicável — "comprar 24 unidades: há 8 disponíveis
e 12 já encomendadas, e a demanda prevista até a próxima entrega, incluindo a
reserva de segurança, é 44" — com a conta visível. Um aviso fixo de "Repor" não
é planejamento, e um alerta de mínimo não é ponto de reposição.

Julgar isso pela presença de condicional no código não diz nada: algoritmo também
usa condicional. O que separa os dois trabalhos é o resultado — primeiro o saldo
precisa estar correto, depois o sistema precisa calcular e explicar quando e
quanto repor.

### Almoxarifado ampliado

Etapa separada: depósitos por loja, recebimento parcial vinculado a compra,
transferência com expedição/recebimento e trânsito, inventário, lote/validade,
quarentena e consumo interno. Definir quem possui mercadoria em trânsito e como
cancelar sem duplicar saldo. Lote vencido ou devolução imprópria não vira saldo
vendável. Rastreabilidade e conversões precedem sugestões avançadas.

## Execução em entregas pequenas

Estado em 07/09/2026: **etapa 1 PARCIAL, com evidência registrada em
[levantamento, reprodução e correção](../quality/inventory-stage-1-evidence.md).
Nenhum gate declarado aprovado.** A etapa 1 responde "recebi, vendi ou perdi:
quanto ficou?" — e nada além disso. Ela não é, e não deve ser apresentada como,
entrega da etapa 3.

"Contar estoque" com verificação de versão foi entregue em 07/09/2026, com as
cinco exigências cobertas e `ADJUSTMENT` restrito por permissão própria. Falta a
**devolução física vinculada à venda**, que é requisito do gate de integridade —
executá-la junto com a etapa 2 muda a sequência, não a pendência. A apresentação
que soma unidades diferentes num cartão só continua aberta no gate de
apresentação.

| Etapa | Entrega | Condição de saída |
|---|---|---|
| 1 — Corrigir movimentos | Contrato de quantidade, transação composta, concorrência, idempotência, propagação de erro e diagnóstico histórico | Gate de integridade aprovado |
| 2 — Completar o fluxo básico | Acervo de estoque independente, ações explícitas, formulários compartilhados, histórico completo, mínimo e correção visual das quatro superfícies | Gates de operação e apresentação aprovados |
| 3 — Ampliar por cenário | Reposição assistida e, em incrementos independentes, depósitos, compras, lotes, receitas e consumo | Gate específico de cada cenário; capacidades incompletas não anunciadas como prontas |

Antes da etapa 1, executor registra commit-base, caminhos de venda, contrato dos
clientes da API e evidência de reprodução. Antes da etapa 2, apresenta desenho das
telas com conteúdo real, nomes longos e estados de erro. O desenho faz parte da
entrega, não substitui a prova funcional. Não há estimativa de prazo inventada aqui.

Diagnóstico histórico somente de leitura procura perdas com variação positiva,
divergência aritmética, duplicações e discrepância entre saldo e movimentos,
considerando saldo de abertura. Exporta identificadores e evidência por loja.
Não presume que toda linha possa ser invertida: investigar origem e preservar
histórico. Correção de dados reais exige decisão nominal e movimentos compensatórios.

## Gates de homologação

### Integridade — automatizado e persistido

- Recebimento positivo aumenta; perda positiva diminui; entradas inválidas são
  recusadas sem movimento, saldo parcial ou sucesso aparente.
- Venda de dois itens com falha no segundo reverte a operação composta; testar
  falta de estoque, retry de pagamento e chamada repetida após timeout.
- Duas vendas concorrentes não vendem a mesma última unidade; contagem com versão
  desatualizada não apaga movimento concorrente.
- Escopo de outra loja/tenant, ator forjado e perfil sem permissão são recusados.
- Devolução física e estorno financeiro exercitados separadamente; serviço não
  cria saldo; itens fracionados mantêm precisão; mudança de mínimo não cria movimento.
- Testar pelos endpoints autenticados, além da unidade de serviço. Busca textual
  por comandos de escrita não substitui teste de comportamento.

### Operação — ciclo pela interface, sem orientação técnica

Em loja de homologação identificada, com produto exclusivo e dados controlados:

| Passo | Ação | Saldo esperado |
|---|---|---|
| 1 | Cadastrar 10 un | 10 |
| 2 | Vender e quitar 2 un | 8 |
| 3 | Receber 5 un pela ação da tela | 13 |
| 4 | Registrar perda de 1 un | 12 |
| 5 | Contar 10 un, conferindo a diferença | 10 |
| 6 | Repetir envio da mesma operação | 10 |
| 7 | Receber devolução apta de 1 un vinculada à venda | 11 |
| 8 | Conferir histórico e recarregar/nova sessão | 11, com as mesmas operações |

Executar também: produto ainda não publicado, mínimo alterado sem movimentação,
produto fora da primeira página, usuário sem permissão, falha de rede e saldo
insuficiente. Exercitar COUNTER e mesa separadamente; declarar bloqueios de
pagamento parcial, crediário ou consumo que não estejam cobertos. O ciclo de
mercadoria pronta não homologa receita/ingredientes.

Uma pessoa representativa do cliente deve localizar recebimento a partir de
“Repor”, registrar perda e explicar o saldo resultante sem dica do desenvolvedor.
Registrar onde hesitou ou precisou de ajuda; uma demonstração guiada não passa
esse critério. O dono do produto valida o resultado, não escolhe detalhes de sinal,
transação ou CSS.

### Apresentação — evidência visual, não apenas ausência de overflow

Conferir Produtos, Estoque, Categorias e Sortimentos em 360, 390, 768, 1024, 1280
e 1440 px de largura; incluir altura 600 px, desktop com zoom de 200%, seletor
aberto, erro de formulário, nome longo e teclado móvel quando disponível.
Guardar capturas do conteúdo e das ações. Proibidos badge partido, botão
inacessível, sobreposição persistente e rolagem horizontal da página para concluir
uma ação essencial. Testes de geometria complementam inspeção humana.

### Liberação — evidência do que foi realmente entregue

Registrar commit testado e implantado, ambiente, data, papel/permissões, cenário,
resultado esperado/obtido e evidências sanitizadas. Separar os estados:
**proposto → implementado → testado automaticamente → homologado pela interface
→ verificado no ambiente publicado**. Nenhum estado implica o seguinte.

Antes de publicar, definir compatibilidade da API, migrações e forma de retorno
seguro; identificar clientes que ainda enviam quantidade assinada. Rodar diagnóstico
histórico no ambiente alvo com acesso apropriado. Não usar transações reais de
cliente como teste exploratório. Após implantação, executar smoke autorizado em
loja de homologação e confirmar persistência e versão.

## Registro de aceite para preencher, não presumir

| Gate | Estado inicial | Evidência necessária |
|---|---|---|
| Integridade | Pendente | testes significativos + reconciliação persistida |
| Operação | Pendente | ciclo completo e navegação sem instrução técnica |
| Apresentação | Pendente | capturas e inspeção nos tamanhos definidos |
| Liberação | Pendente | diagnóstico, decisão de dados e commit publicado verificado |
| Almoxarifado ampliado | Fora da entrega básica | contrato e aceite por incremento |

O agente executor deve devolver mudanças, testes executados, cenários realmente
homologados e limites restantes. Não concluir com “a função existe”, soma de testes
verdes ou pedido genérico para o dono decidir a implementação.
