# UX-01 — sete áreas, hubs de cards e um histórico que volta

Data: 08/09/2026 · base: [baseline da UX-00](ux-00-baseline-2026-09-08.md) ·
trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md).

A UX-00 mediu seis atritos. Quatro deles tinham a mesma causa: **o módulo aberto
era estado do componente e a URL era um espelho**, escrito com `replaceState`.
Nada era empilhado, então voltar não voltava; e um endereço que ninguém
reconhecia caía calado na visão geral. Esta sprint troca a causa, não os
sintomas: a URL passa a ser o estado, e o histórico volta a ser do navegador.

## O que mudou, e onde a decisão mora

| Decisão | Onde |
|---|---|
| A área de cada destino e a frase que ele promete são **dado da malha** | migração `090_the_mesh_carries_the_area` |
| URL → estado, e estado → URL, como função pura | `frontend/src/domain/managementNavigation.ts` |
| Entrada → hub → módulo, foco e módulos vivos | `frontend/src/layouts/ManagementLayout.tsx` |
| Grade de cards reutilizável | `frontend/src/components/management/AreaHub.tsx` |

As sete áreas **não estão escritas no componente**. Cada contribuição declara em
`metadata_json.area` a chave, o rótulo e a ordem da sua área, e em
`description` a frase de tarefa do card — pelo mesmo motivo que a palavra do
nicho virou dado na 088: quem abrir uma área nova insere linha, não edita código
de projeção. Uma contribuição sem área declarada **não vira card**: o contrato
proíbe inventar destino para completar sete itens.

Três coisas que a migração grava e que não são cosméticas:

1. **A visão geral deixou de ser área.** A linha continua existindo, com a mesma
   permissão `management.read`, marcada como `placement: ENTRY`. Ela é o
   conteúdo da entrada, não a oitava aba que o contrato proíbe.
2. **Provedores de pagamento saiu de Administração para Financeiro**, que é onde
   configurar recebimento pertence. Capacidade `tef` e permissão `provider.read`
   não mudaram: mudou o lugar, não a autorização.
3. **"Estoque" virou "Estoques"**, a correção de escrita pedida no mapa.

## Os seis atritos, remedidos na tela

Roteiro: `frontend/e2e/presentation/ux01_navigation.cjs`. Relatório e capturas em
[`evidence/ux-01/`](evidence/ux-01/).

| # | Atrito da UX-00 | O que a medida devolve agora |
|---|---|---|
| A1 | Voltar caía em `?module=subscription` | Do módulo, voltar dá **Mercadorias**; voltar de novo dá a entrada; avançar volta a Mercadorias |
| A2 | Foco ficava no botão da barra | `activeElement` é o `H1` da tela nova, dentro do `main` |
| A3 | Filtro digitado sumia ao retornar | "coca" digitado em Produtos continua lá depois de ir ao hub e voltar |
| A4 | `?module=fornecedores` caía calado na visão geral | "Este destino não está disponível", dizendo qual endereço foi pedido |
| A5 | Destino não autorizado abria tela em branco | Mesma tela do A4 — `?module=tables` sem `FOOD_SERVICE` diz o que houve |
| A6 | Escape não fechava a gaveta do celular | A gaveta **deixou de existir**: no celular as áreas são o conteúdo |

**O que já funcionava e continua**: link direto abre o módulo, atualizar preserva,
e o link legado `?module=inventory` segue funcionando — reescrito no lugar para
`?area=MERCADORIAS&module=inventory`, com `replaceState`, para o primeiro voltar
não devolver ao mesmo endereço em laço.

### A dobra, medida do mesmo jeito

A UX-00 mediu, em 1366×640 — a tela do balcão —, **5 dos 13 destinos abaixo da
dobra**, Estoques entre eles. Agora a entrada tem sete áreas e **nenhuma fica
abaixo da dobra** nesse tamanho.

No celular, três das sete áreas exigem rolar. Isso **não** é tratado como falha:
a dobra da UX-00 era sobre a tela fixa do balcão, onde rolar a barra para achar
Estoques é defeito; rolar a página num telefone é o idioma do aparelho. O que o
roteiro exige no celular é outra coisa — que as sete estejam lá e que a página
não role para o lado.

## Como sei que a medida acusa

Duas correções de método nesta sprint, ambas porque a medida errou antes de
acertar:

- **A medida leu a barra escondida.** No celular há dois `nav` com o mesmo nome —
  a barra do desktop, oculta por CSS, e os cards. Pegar o primeiro do documento
  fazia o celular ser medido pela barra que ele não vê, e a dobra dava zero por
  um motivo falso. Corrigido para escolher o retângulo aparente; aí a medida
  passou a acusar as três áreas abaixo da dobra. **É a segunda vez que presença
  no DOM foi confundida com visibilidade nesta trilha.**
- **O roteiro passou com a correção desfeita.** Desfiz de propósito o conserto do
  `navigateTo` — a comparação que só olhava o `pathname` — e o roteiro continuou
  dando zero falhas, porque ele nunca clicava em "Menu principal": só usava
  `goBack` e endereço direto, e nenhum dos dois passa por ali. O roteiro ganhou
  esse clique. Com a regressão, ele reprova; sem ela, passa. **Medida que não
  toca o botão não prova o botão.**

## O contrato de navegação, item a item

| Item | Estado |
|---|---|
| 1 — entrada com exatamente as sete áreas, sem oitava aba | **entregue**; a Visão geral segue como conteúdo inicial autorizado |
| 2 — escolher área oculta a barra e mostra cards | **entregue** |
| 3 — topo com apenas Menu principal e Sair | **entregue**; "Validar no PDV" desceu para o conteúdo de Operação |
| 4 — "Voltar para Mercadorias" leva ao hub; Menu principal leva à entrada | **entregue**, sem "Voltar" ambíguo |
| 5 — voltar/avançar, atualizar, link direto, filtros e `?module=` | **entregue** |
| 6 — foco no título ao navegar e no card ao voltar | **entregue**; a gaveta do celular deixou de existir |
| 7 — autorização vem das contribuições e do servidor | **preservada**; mesas continuam presas a `FOOD_SERVICE` |

Sobre o item 3: o contrato manda "Validar no PDV" para "o conteúdo de
Operação/Vendas". Ficou no **hub de Operação**, como um bloco com a frase que
explica o que acontece, e não dentro do módulo Vendas — assim a sprint não
reescreve a lógica de `SalesHistory`, que é o que o próprio enunciado pede. Se a
intenção era dentro de Vendas, é uma linha para mover na UX-05.

Sobre Provedores de pagamento: o mapa o descreve como "acessível dentro de
Financeiro/Crediário e Recebíveis e por link direto autorizado". Entendi como
card em Financeiro — que é discoverable, não cria oitava área e mantém o link
direto. Se a intenção era escondê-lo dentro do módulo de Recebíveis, é mudar a
área na malha, sem tocar em código.

## O que não mudou nesta sprint

Nenhum módulo teve lógica reescrita: os quatorze componentes existentes entram no
novo estado como estavam. Os quatro destinos ausentes do mapa — Fornecedores,
Contas a pagar, Comissões e gorjetas, Manutenção — **continuam ausentes**, sem
card e sem botão morto, até UX-09..UX-12.

## Portões executados

| Portão | Resultado |
|---|---|
| `npm test` (frontend) | 180 passando, 0 falhas — 11 novos em `management_navigation.test.ts` |
| `npm run build` (tsc + vite) | limpo |
| `pytest` dos testes de malha e navegação | 18 passando, incluindo `test_management_areas_mesh.py` |
| `alembic check` | sem operações novas |
| Roteiro `ux01_navigation.cjs` | 9 telas, 8 medições, 0 falhas — e reprova com a regressão de controle |

Quatro guardas existentes (`shell_boundaries`, `s7-table-service`,
`s10-channel-hub`, `s13-1-backoffice`) liam o texto-fonte do `ManagementLayout`
para provar que a navegação só mostra o que o servidor autoriza. A regra não
mudou de valor, mudou de lugar: os guardas passaram a ler
`managementNavigation.ts`. Nenhum foi removido.

### A auditoria responsiva voltou a rodar

`responsive_audit.cjs` navegava clicando no rótulo do card e no botão "Abrir
menu". Ele já estava quebrado **antes desta sprint** — parou de achar
"Sortimentos" quando a 088 renomeou o card para "Catálogos" —, e a UX-01
teria quebrado o resto ao remover a gaveta. Como ele não está no CI, ninguém
soube.

O roteiro passou a navegar por endereço canônico (`?area=…&module=…`), que é o
que os testes de navegação já vigiam. O que ele mede é a tipografia da tela, não
o caminho até ela. Rodando de novo: **20 de 20 medições, 0 achados** —
palavra partida e transbordo horizontal seguem zerados nas quatro telas de
Mercadorias, em quatro tamanhos.
