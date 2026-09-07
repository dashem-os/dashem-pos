# Etapa 2 — correção visual e operacional das quatro superfícies

Segunda rodada, respondendo aos cinco pontos levantados na revisão da primeira.
As capturas de desktop estão em `desktop/` (todas em 1660 × 860) e a verificação
responsiva em `responsivo/`, com relatório em JSON.

## Os cinco pontos, e o que foi feito

### 1. O histórico chamava de "Conferência" também o ajuste técnico

Era tradução errada, e apagava na tela a separação que a permissão mantém no
servidor. O tipo do movimento registra o **efeito**; ele nunca registrou o
**caminho**. Agora registra: a migração `085` acrescenta
`inventory_movements.origin`, e quem produz o movimento assina — a conferência
grava `COUNT`, o ajuste técnico grava `TECHNICAL_ADJUSTMENT`.

| Origem gravada | Como o histórico lê |
|---|---|
| `COUNT` | **Contagem de estoque** |
| `TECHNICAL_ADJUSTMENT` | **Ajuste técnico** |
| nula (histórico anterior à marca) | **Ajuste** |

O preenchimento retroativo só alcança o que já estava **provado por outro
fato**: `inventory_counts.movement_id` aponta para o movimento que a conferência
produziu, e essas linhas recebem `COUNT`. **Nenhuma linha recebe
`TECHNICAL_ADJUSTMENT` por eliminação** — o ajuste técnico não deixava marca
antes desta migração, e deduzi-lo da ausência de contagem seria afirmar origem
onde só existe desconhecimento.

Provado em `test_a_count_and_a_technical_adjustment_do_not_look_alike_in_the_history`
e `test_the_count_that_signs_its_movement_is_the_one_linked_to_it`, que confere
a origem contra o vínculo já existente — se as duas divergirem, uma está
mentindo.

### 2. "Entrada ou perda" juntava duas intenções

Agora são duas ações. **Receber** é botão direto na linha, nas duas telas que
mexem em estoque; **Registrar perda** vive no menu de ações, junto do ajuste
técnico. O formulário perdeu o seletor de tipo: ele abre já sendo a operação que
foi escolhida, com título, rótulo do campo e botão de confirmação
correspondentes — "Quantidade recebida" ou "Quantidade perdida". Quem precisa
repor clica em Receber e digita quanto chegou.

### 3. Uma captura de desktop não demonstra a classe inteira do problema

Correto, e `break-word` de fato não é garantia universal — o resultado depende
da largura e do layout. Então a verificação deixou de ser visual.

`frontend/e2e/presentation/responsive_audit.cjs` percorre as quatro superfícies
em quatro tamanhos e **mede**, no layout já renderizado:

* **palavra partida** — para cada sequência sem oportunidade natural de quebra
  (sem hífen, barra ou travessão), um `Range` sobre ela devolve os retângulos
  que ela ocupa. Retângulos em mais de uma linha significam palavra partida no
  meio. É o defeito medido no resultado, não no CSS declarado;
* **transbordo horizontal** — `scrollWidth` do documento maior que a largura
  visível, que é o outro lado da moeda: o que impede a palavra de partir pode
  empurrar a página.

| Tamanho | Situação |
|---|---|
| 390 × 844 (celular em retrato) | 5 medições, 0 achados |
| 834 × 1112 (tablet em retrato) | 5 medições, 0 achados |
| 1366 × 640 (altura reduzida) | 5 medições, 0 achados |
| 1107 × 573 (zoom de 150% sobre 1660 × 860) | 5 medições, 0 achados |

**E a medida foi validada contra o defeito conhecido.** Uma medição que nunca
acusa não prova nada, então rodei a mesma auditoria com o CSS anterior
(`overflow-wrap: anywhere`) restaurado:

| Execução | Medições | Com achado | Palavras partidas |
|---|---|---|---|
| Controle, CSS anterior | 20 | **12** | **139** |
| Corrigido | 20 | **0** | **0** |

No controle as mais frequentes foram `Receber` (45), `Contar` (30), `Editar`
(21), `Produto` (15) e `Ativo` (6) — exatamente as palavras das suas capturas.
Os dois relatórios estão em `responsivo/`.

O que isso demonstra e o que não demonstra: **nestas quatro telas, nestes quatro
tamanhos, com este conteúdo, nenhuma palavra parte e nenhuma página transborda**.
Não é prova de que nenhuma largura futura parta nenhuma palavra — a auditoria
fica no repositório para ser executada de novo quando a tela mudar.

### 4. Categorias entrou nesta rodada

A quarta superfície foi corrigida em vez de ficar pendente. O **Slug** deixou de
ser tarefa de quem cadastra: ele nasce do nome enquanto a pessoa digita, e o
campo só aparece atrás de "Ajustar a referência usada por integrações", já
mostrando o valor derivado. O cartão parou de exibir a referência técnica ao
lado do nome, e o cabeçalho trocou "Estruture a navegação do PDV sem depender da
ordem dos produtos ou de nomes implícitos" por "Agrupe o que é parecido para
achar mais rápido na hora de vender".

### 5. A imagem vinha antes do preço

Tipo e preço subiram para antes do bloco de mídia. A foto ajuda a reconhecer o
item na tela de venda; o preço é o que decide se ele pode ser vendido — e o
bloco de imagem, com o seu aviso, ocupava metade do formulário antes de a pessoa
chegar ao campo que ela veio preencher.

## As capturas de desktop

| # | Arquivo | O que mostra |
|---|---|---|
| 1 | `01-produtos-lista.png` | Estoque rotulado, nomes longos inteiros, ação **Receber** |
| 2 | `02-produtos-mais-acoes.png` | Menu com registrar perda, acesso rápido, arquivar e excluir |
| 3 | `03-produtos-editar-preenchido.png` | Preço antes da foto; inclui o aviso real de armazenamento indisponível neste ambiente |
| 4 | `04-estoque-lista.png` | Colunas rotuladas e os quatro estados de situação |
| 5 | `05-estoque-entrada-preenchida.png` | "Receber mercadoria", campo "Quantidade recebida" |
| 6 | `06-estoque-entrada-concluida.png` | Depois do recebimento aceito |
| 7 | `07-estoque-mais-acoes.png` | Registrar perda e ajuste técnico fora da linha |
| 8 | `08-estoque-erro-recusa-do-servidor.png` | **Erro real**: perda de 999 com 27 na prateleira, recusada pelo servidor e mostrada no formulário |
| 9 | `09-estoque-contagem-com-diferenca.png` | Saldo lido e diferença calculada à vista |
| 10 | `10-estoque-depois-das-acoes.png` | Saldo e situação depois da conferência |
| 11 | `11-estoque-historico-legivel.png` | **Contagem de estoque +4 UN** e **Entrada +24 UN** |
| 12 | `12-sortimentos-lista.png` | "Onde é vendido", "Ainda não publicado", sem coluna de versão |
| 13 | `13-categorias-lista.png` | Cartões sem a referência técnica |
| 14 | `14-categorias-nova-sem-slug.png` | Cadastro com nome preenchido e a referência derivada atrás de um clique |

## Como as capturas foram feitas

* banco **local**, criado do zero e migrado até `085`. **Nada foi escrito em
  produção**;
* conteúdo semeado por `backend/tests/support/seed_presentation_walkthrough.py`
  com o acervo real do tenant de homologação, lido em modo somente leitura, mais
  os dois nomes mais longos do acervo do sistema, uma mercadoria zerada e um
  serviço;
* API e frontend reais, permissões reais de `TENANT_OWNER`, recusa vinda do
  servidor. A sessão de gestão é escrita no armazenamento do navegador com um
  token assinado pelo segredo de teste: **nenhum código de produto foi alterado
  para autenticar**;
* roteiros repetíveis em `frontend/e2e/presentation/`.

## O que continua pendente, explicitamente

* **O portão de apresentação não está aprovado.** Aprovar é decisão do dono do
  produto, olhando estas telas; o que está aqui é a inspeção técnica e a
  demonstração dos critérios;
* **o portão de operação segue pendente**: exige o ciclo completo pela navegação
  real, com pessoa representativa do cliente;
* `test_negotiation_sale_stock.py` falha **no meu banco local**, por privilégio
  insuficiente do papel que uso nas fixtures. Verifiquei que falha igual com e
  sem estas alterações — guardando o trabalho e rodando na base limpa — então
  não é regressão desta rodada. Quem dá o veredito é o CI, que usa banco
  próprio; até ele responder, isto fica registrado como não verificado.
